import os
import time
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)

from app.router.auth_router        import router as auth_router
from app.router.chat_router        import router as chat_router
from app.router.appointment_router import router as appointment_router
from app.router.dashboard_router   import router as dashboard_router, start_snapshot_background_task

from app.fhir.bootstrap                    import load_fhir_repository
from app.services.fhir_schedule_service    import FHIRScheduleService
from app.services.fhir_appointment_service import FHIRAppointmentService
from app.services.appointment_service      import AppointmentService
from app.services.memory_service           import load_member_memory
from app.services.calendar_service         import check_provider_availability

logger = logging.getLogger("app")

app = FastAPI(title="Provider Search Agentic Platform", version="6.0.0")

_cors_origins = os.getenv("CORS_ORIGINS", "*")
_allow_origins = [o.strip() for o in _cors_origins.split(",")] if _cors_origins != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start    = time.perf_counter()
    response = await call_next(request)
    ms       = (time.perf_counter() - start) * 1000
    logger.info("%s %s  →  %d  (%.0fms)", request.method, request.url.path, response.status_code, ms)
    return response

# ── FHIR in-memory provider directory ────────────────────────────────────────
repo                 = load_fhir_repository()
schedule_service     = FHIRScheduleService(repo)
appointment_fhir_svc = FHIRAppointmentService(repo)
appointment_service  = AppointmentService(
    schedule_service   = schedule_service,
    appointment_service= appointment_fhir_svc,
)
app.state.fhir_repo           = repo
app.state.appointment_service = appointment_service

# ── FastAPI routers ───────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(appointment_router)
app.include_router(dashboard_router)

# ── Background tasks + cache warm-up on startup ─────────────────────────────
@app.on_event("startup")
async def _on_startup():
    start_snapshot_background_task()
    # Pre-warm the member summary cache so the first dashboard request is instant
    from app.router.dashboard_router import MEMBER_IDS, _get_cached_summary
    from fastapi.concurrency import run_in_threadpool
    import asyncio as _asyncio
    try:
        await _asyncio.gather(
            *[run_in_threadpool(_get_cached_summary, mid) for mid in MEMBER_IDS]
        )
        logger.info("Dashboard summary cache warmed for %d members", len(MEMBER_IDS))
    except Exception as _e:
        logger.warning("Cache warm-up failed (non-fatal): %s", _e)

# ── Memory endpoint (frontend calls /memory/{member_id}) ─────────────────────
@app.get("/memory/{member_id}")
def get_memory(member_id: str):
    return load_member_memory(member_id)

# ── Availability endpoint (frontend calls /availability) ─────────────────────
@app.post("/availability")
async def get_availability(request: Request):
    body = await request.json()
    npi               = body.get("npi", "")
    provider_name     = body.get("provider_name", "")
    city              = body.get("city", "")
    consultation_mode = body.get("consultation_mode", "Both")
    selected_date     = body.get("selected_date", "")
    client_time       = body.get("client_time", "")   # "HH:MM" in provider's local tz (PST)
    client_date       = body.get("client_date", "")   # "YYYY-MM-DD" browser local date
    is_initial        = bool(body.get("is_initial", False))

    if not npi:
        return JSONResponse({"error": "npi is required"}, status_code=400)

    result = check_provider_availability(
        npi=npi,
        provider_name=provider_name,
        city=city,
        consultation_mode=consultation_mode,
        appointment_date=selected_date,
        client_time=client_time,
        client_date=client_date,
        no_advance=bool(selected_date) and not is_initial,  # modal picked a specific date — don't skip ahead unless on initial mount
    )
    # Use all_day_slots if available (full 8am–5pm with past/booked flags)
    # Fall back to available_slots for backward compat
    raw_slots = result.get("all_day_slots") or [
        {"time_24h": s.get("time_24h", ""), "time_display": s["time_display"],
         "past": False, "booked": False}
        for s in result.get("available_slots", [])
    ]

    all_slots = [
        {
            "time_display": s["time_display"],
            "time_24h":     s.get("time_24h", ""),
            "type":         consultation_mode,
            # merge past into booked so frontend only needs to check s.booked
            "booked":       s.get("past", False) or s.get("booked", False),
            "past":         s.get("past", False),
        }
        for s in raw_slots
    ]
    return {**result, "all_slots": all_slots}

# ── Static frontend (must be mounted BEFORE ADK catch-all) ──────────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def root():
    index = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index):
        return JSONResponse({"status": "ok", "message": "API running"}, status_code=200)
    return FileResponse(index)

@app.get("/health")
def health():
    return {"status": "ok", "version": "6.0.0"}

# ── Dev endpoints — prior auth toggling ──────────────────────────────────────

class TogglePriorAuthRequest(BaseModel):
    member_id: str

@app.post("/dev/toggle-prior-auth")
def toggle_prior_auth(req: TogglePriorAuthRequest):
    from app.services.storage_service import storage
    from app.adk import agent
    new_status = storage.toggle_prior_auth_status(req.member_id)
    if hasattr(agent, "_runners"):
        for k in [k for k in list(agent._runners.keys()) if k.startswith(f"{req.member_id}|")]:
            agent._runners.pop(k, None)
    return {"member_id": req.member_id, "new_status": new_status}

@app.get("/dev/prior-auth-status/{member_id}")
def get_prior_auth_status(member_id: str):
    from app.services.storage_service import storage
    data = storage.get_prior_auth(member_id)
    if not data:
        return {"member_id": member_id, "status": "no_file"}
    return {"member_id": member_id, "status": data.get("status", "none"), "data": data}


# ── Demo reset endpoint ───────────────────────────────────────────────────────

@app.post("/dev/reset-demo")
def reset_demo(dry_run: bool = False, clear_all: bool = False):
    """
    Resets demo data for MEM-10004 and MEM-10006.
    - dry_run=true  : shows what would be done without making changes
    - clear_all=true: clears ALL members first (via clear_member_logs.py), then reseeds
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from reset_demo import clear_member, seed_mem_10004, seed_mem_10006, DEMO_MEMBERS
    try:
        from clear_member_logs import clear_all_members
    except Exception:
        clear_all_members = None

    today = datetime.now()
    log: list[str] = []

    # Monkey-patch print to capture output
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        if clear_all:
            if clear_all_members:
                clear_all_members(dry_run=dry_run)
            else:
                for mid in DEMO_MEMBERS:
                    clear_member(mid, dry_run)
        else:
            for mid in DEMO_MEMBERS:
                clear_member(mid, dry_run)

        seed_mem_10004(today, dry_run)
        seed_mem_10006(today, dry_run)

    log = [line for line in buf.getvalue().splitlines() if line.strip()]
    return {
        "status":  "dry_run" if dry_run else "ok",
        "dry_run": dry_run,
        "clear_all": clear_all,
        "members_reset": DEMO_MEMBERS,
        "log": log,
    }


