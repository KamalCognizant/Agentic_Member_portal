from fastapi import APIRouter, Request
from app.services.storage_service import storage

router = APIRouter(prefix="/appointments", tags=["Appointments"])


@router.get("/{member_id}")
def get_member_appointments(member_id: str):
    """Return all appointments for a member (upcoming + past)."""
    appointments = storage.read(f"appointments/{member_id}.json") or []
    return {"appointments": appointments}


@router.patch("/{member_id}/cancel")
async def cancel_member_appointment(member_id: str, request: Request):
    """Mark a specific appointment as cancelled by provider + date."""
    body = await request.json()
    provider = (body.get("provider_name") or body.get("provider", "")).strip().lower()
    date = (body.get("date", "") or "").strip()
    key = f"appointments/{member_id}.json"
    appts = storage.read(key) or []
    matched = False
    for a in appts:
        a_provider = (a.get("provider_name") or a.get("provider", "")).strip().lower()
        a_date = (a.get("date", "") or "").strip()
        if a_provider == provider and a_date == date:
            a["status"] = "cancelled"
            matched = True
            break
    if matched:
        storage.write(key, appts)
        # Also cancel in bookings store
        bk_key = f"bookings/{member_id}.json"
        bookings = storage.read(bk_key) or []
        for b in bookings:
            b_provider = (b.get("provider_name") or b.get("provider", "")).strip().lower()
            b_date = (b.get("date", "") or "").strip()
            if b_provider == provider and b_date == date:
                b["status"] = "cancelled"
                break
        storage.write(bk_key, bookings)
        return {"success": True}
    return {"success": False, "message": "Appointment not found"}

@router.post("/{member_id}")
async def save_member_appointment(member_id: str, request: Request):
    """Save a confirmed appointment for a member (called by frontend after booking)."""
    body = await request.json()
    key = f"appointments/{member_id}.json"
    appts = storage.read(key) or []

    # Reject overlapping appointments at the same date + time, regardless of provider.
    new_date = (body.get("date", "") or "").strip()
    new_time = ((body.get("time", "") or body.get("time_start", "")) or "").strip()
    new_provider = (body.get("provider_name") or body.get("provider", "")).strip()
    if new_date and new_time:
        for a in appts:
            existing_date = (a.get("date", "") or "").strip()
            existing_time = ((a.get("time", "") or a.get("time_start", "")) or "").strip()
            existing_provider = (a.get("provider_name", a.get("provider", "")) or "").strip()
            if existing_date and existing_time and existing_date == new_date and existing_time == new_time:
                # Same provider + same slot = telehealth conversion, not a conflict — allow update
                if existing_provider.lower() == new_provider.lower():
                    break
                return {
                    "success": False,
                    "message": f"You already have an appointment with {existing_provider} at {new_date} {new_time}. Would you like to choose a different time?",
                    "appointments": appts,
                }

    # Same provider + date: update in place (handles telehealth conversion)
    provider_name = body.get("provider_name") or body.get("provider", "")
    new_record = {
        "provider_name":     provider_name,
        "provider":          provider_name,
        "date":              body.get("date", ""),
        "time":              body.get("time", "") or body.get("time_start", ""),
        "time_start":        body.get("time_start", "") or body.get("time", ""),
        "consultation_type": body.get("consultation_type", ""),
        "address":           body.get("address", ""),
        "reason":            body.get("reason", ""),
        "specialty":         body.get("specialty", ""),
        "npi":               body.get("npi", ""),
    }
    for i, a in enumerate(appts):
        if (
            (a.get("provider_name", a.get("provider", "")) or "").lower() == provider_name.lower()
            and (a.get("date", "") or "") == new_record["date"]
        ):
            appts[i] = new_record
            storage.write(key, appts)
            return {"success": True, "appointments": appts}
    appts.append(new_record)
    storage.write(key, appts)
    return {"success": True, "appointments": appts}
