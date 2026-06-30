"""
reset_demo.py - Clears all logs for demo members then re-seeds fresh demo data.
               Run this before every demo session.

Usage (from the updated_backend/ directory):
    python reset_demo.py              -- clears + reseeds MEM-10004 and MEM-10006
    python reset_demo.py --dry-run    -- shows what would be deleted/written without doing it
    python reset_demo.py --clear-all  -- clears ALL members (via clear_member_logs.py) then reseeds demo members

What it does per member:
  MEM-10004: wipe all logs -> seed upcoming in-person appointment 3 days from today
  MEM-10006: wipe all logs -> seed completed appointment 3 days ago + MRI prescription + prior_auth
"""

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import true

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Attempt to reuse clear_all_members from clear_member_logs.py if available
try:
    from clear_member_logs import clear_all_members
except Exception:
    clear_all_members = None

# ── Config ────────────────────────────────────────────────────────────────────
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "provider_search_applicationstore")
GCP_PROJECT_ID  = os.getenv("GCP_PROJECT_ID")

BASE_DIR  = Path(__file__).resolve().parent
STORE_DIR = BASE_DIR / "logs" / "storage"
LOGS_DIR  = BASE_DIR / "logs"

STORAGE_SUBDIRS = [
    "bookings", "conversations", "history_summary", "long_term_profile",
    "mri_prescription", "prior_auth", "referral", "pcp_changes",
    "plan_change", "notifications", "appointments",
]

CONVERSATION_DIRS = [
    LOGS_DIR / "conversation" / "json",
    LOGS_DIR / "conversation" / "txt",
    LOGS_DIR / "health_memory",
    LOGS_DIR / "explainability",
]

DEMO_MEMBERS = ["MEM-10004", "MEM-10006"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt(dt: datetime) -> str:
    """Format date as 'June 10, 2026' style (no leading zero on day)."""
    return dt.strftime("%B %d, %Y").replace(" 0", " ")


def _delete(path: Path, dry_run: bool):
    if path.exists():
        if dry_run:
            print(f"  [dry-run] would delete: {path.relative_to(BASE_DIR)}")
        else:
            path.unlink()
            print(f"  deleted: {path.relative_to(BASE_DIR)}")


def _write(path: Path, data: dict | list, dry_run: bool):
    if dry_run:
        print(f"  [dry-run] would write:  {path.relative_to(BASE_DIR)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote:   {path.relative_to(BASE_DIR)}")


def _get_gcs_bucket():
    try:
        from google.cloud import storage as gcs
        return gcs.Client(project=GCP_PROJECT_ID).bucket(GCS_BUCKET_NAME)
    except Exception:
        return None


# ── Step 1: Clear ─────────────────────────────────────────────────────────────

def clear_member(member_id: str, dry_run: bool):
    print(f"\n  Clearing {member_id}...")

    # Storage subdir files
    for subdir in STORAGE_SUBDIRS:
        _delete(STORE_DIR / subdir / f"{member_id}.json", dry_run)

    # Conversation + memory dirs
    for conv_dir in CONVERSATION_DIRS:
        if conv_dir.exists():
            for f in conv_dir.glob(f"{member_id}*"):
                _delete(f, dry_run)

    # Wildcard catch-all under logs/
    seen = {STORE_DIR / s / f"{member_id}.json" for s in STORAGE_SUBDIRS}
    for f in LOGS_DIR.rglob(f"{member_id}*"):
        if f.is_file() and f not in seen:
            _delete(f, dry_run)

    # GCS (best-effort, non-blocking)
    bucket = _get_gcs_bucket()
    if bucket:
        for subdir in STORAGE_SUBDIRS:
            key = f"{subdir}/{member_id}.json"
            try:
                blob = bucket.blob(key)
                if blob.exists():
                    if dry_run:
                        print(f"  [dry-run] would delete GCS: {key}")
                    else:
                        blob.delete()
                        print(f"  deleted GCS: {key}")
            except Exception:
                pass


# ── Step 2: Seed ──────────────────────────────────────────────────────────────

def seed_mem_10004(today: datetime, dry_run: bool):
    upcoming      = today + timedelta(days=3)
    upcoming_date = fmt(upcoming)
    print(f"\n  Seeding MEM-10004 -> upcoming appointment on {upcoming_date}")

    _write(STORE_DIR / "appointments/MEM-10004.json", [
        {
            "provider_name":     "Dr. LAWRENCE ABRAMSON",
            "provider":          "Dr. LAWRENCE ABRAMSON",
            "date":              upcoming_date,
            "time":              "10:30 AM",
            "time_start":        "10:30 AM",
            "consultation_type": "In-Person",
            "address":           "",
            "reason":            "skin rashes",
            "specialty":         "Dermatology",
            "npi":               "1891766903",
        }
    ], dry_run)

    _write(STORE_DIR / "bookings/MEM-10004.json", [
        {
            "status":            "confirmed",
            "provider_name":     "Dr. LAWRENCE ABRAMSON",
            "npi":               "1891766903",
            "date":              upcoming_date,
            "time_start":        "10:30 AM",
            "time_end":          "11:00 AM",
            "timezone":          "EST",
            "consultation_type": "In-Person",
            "reason":            "skin rashes",
            "visit_note":        "Please arrive 15 minutes early for check-in.",
            "saved_at":          today.isoformat(),
        }
    ], dry_run)


def seed_mem_10006(today: datetime, dry_run: bool):
    past      = today - timedelta(days=3)
    past_date = fmt(past)
    print(f"\n  Seeding MEM-10006 -> completed appointment on {past_date} + MRI prescription + prior_auth")

    _write(STORE_DIR / "appointments/MEM-10006.json", [
        {
            "provider_name":     "Dr. ABED ABDELAZIZ",
            "provider":          "Dr. ABED ABDELAZIZ",
            "date":              past_date,
            "time":              "4:10 PM",
            "time_start":        "4:10 PM",
            "consultation_type": "In-Person",
            "address":           "",
            "reason":            "lower back pain due to fall",
            "specialty":         "Orthopaedic Surgery, Sports Medicine",
            "npi":               "1699262709",
        }
    ], dry_run)

    _write(STORE_DIR / "bookings/MEM-10006.json", [
        {
            "status":            "completed",
            "provider_name":     "Dr. ABED ABDELAZIZ",
            "npi":               "1699262709",
            "date":              past_date,
            "time_start":        "4:30 PM",
            "time_end":          "5:00 PM",
            "timezone":          "PST",
            "consultation_type": "In-Person",
            "reason":            "lower back pain due to fall",
            "visit_note":        "Please arrive 15 minutes early for check-in.",
        }
    ], dry_run)

    _write(STORE_DIR / "mri_prescription/MEM-10006.json", {
        "prescription_mri": True,
        "body_part":        "lower back",
        "procedure":        "MRI Lumbar Spine",
        "reason":           "lower back pain due to fall - rule out disc herniation",
        "prescribed_by": {
            "name":      "Dr. ABED ABDELAZIZ",
            "specialty": "Orthopaedic Surgery, Sports Medicine",
            "npi":       "1699262709",
        },
        "prescribed_date": past.strftime("%Y-%m-%d"),
    }, dry_run)

    _write(STORE_DIR / "prior_auth/MEM-10006.json", {
        "status":                "none",
        "auth_reference_number": "",
        "submitted_by":          "",
        "submitted_date":        "",
        "approved_date":         "",
        "valid_through":         "",
        "payer":                 "Cigna",
    }, dry_run)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset demo data for MEM-10004 and MEM-10006.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes.")
    parser.add_argument("--clear-all", action="store_true", help="Clear ALL members (uses clear_member_logs.py) before seeding demo data.")
    args = parser.parse_args()

    today = datetime.now()
    label = "[DRY-RUN] " if args.dry_run else ""

    # If requested, clear all members using clear_member_logs.py's implementation
    if args.clear_all:
        if clear_all_members is None:
            print("clear_member_logs.py not available — cannot --clear-all. Falling back to per-demo-member clear.")
            print(f"\n{label}=== Step 1: Clear logs (demo members only) ===")
            for member_id in DEMO_MEMBERS:
                clear_member(member_id, args.dry_run)
        else:
            print(f"\n{label}=== Step 1: Clearing ALL members (via clear_member_logs.py) ===")
            clear_all_members(dry_run=args.dry_run)
    else:
        print(f"\n{label}=== Step 1: Clear logs ===")
        for member_id in DEMO_MEMBERS:
            clear_member(member_id, args.dry_run)

    print(f"\n{label}=== Step 2: Seed demo data ===")
    seed_mem_10004(today, args.dry_run)
    seed_mem_10006(today, args.dry_run)

    print(f"\n{label}Done.")
