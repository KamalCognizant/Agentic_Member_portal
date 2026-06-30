# """
# Calendar Service — timezone-aware appointment scheduling.
# Generates deterministic mock calendars per provider+date (NPI-seeded).
# Persists real bookings to appointments.json so they survive restarts.
# """

# import hashlib
# import json
# import os
# import random
# from datetime import datetime, timedelta

# # ── Timezone map ──────────────────────────────────────────────────────────────
# CITY_TIMEZONE = {
#     "los angeles": {"tz_name": "PST", "utc_offset": -8},
#     "new york":    {"tz_name": "EST", "utc_offset": -5},
#     "miami":       {"tz_name": "EST", "utc_offset": -5},
#     "chicago":     {"tz_name": "CST", "utc_offset": -6},
#     "houston":     {"tz_name": "CST", "utc_offset": -6},
#     "seattle":     {"tz_name": "PST", "utc_offset": -8},
#     "dallas":      {"tz_name": "CST", "utc_offset": -6},
#     "austin":      {"tz_name": "CST", "utc_offset": -6},
# }

# SHIFT_TYPES = {
#     "Early Bird":   {"start": "07:00", "end": "15:00"},
#     "Standard":     {"start": "09:00", "end": "17:00"},
#     "Late Shift":   {"start": "11:00", "end": "19:00"},
#     "Morning Only": {"start": "08:00", "end": "12:00"},
# }

# _APPOINTMENTS_FILE = os.path.join(
#     os.path.dirname(__file__), "..", "..", "logs", "appointments.json"
# )
# _calendar_cache: dict = {}


# # ── Persistence ───────────────────────────────────────────────────────────────

# def _load_appointments() -> dict:
#     try:
#         if os.path.exists(_APPOINTMENTS_FILE):
#             with open(_APPOINTMENTS_FILE, "r") as f:
#                 return json.load(f)
#     except Exception:
#         pass
#     return {}


# def _save_appointments(data: dict):
#     os.makedirs(os.path.dirname(_APPOINTMENTS_FILE), exist_ok=True)
#     try:
#         with open(_APPOINTMENTS_FILE, "w") as f:
#             json.dump(data, f, indent=2)
#     except Exception:
#         pass


# _booked_store: dict = _load_appointments()
# _calendar_cache: dict = {}  # cleared on every server start — fresh calendars each session


# # ── Helpers ───────────────────────────────────────────────────────────────────

# def _get_timezone(city: str) -> dict:
#     city_lower = city.lower().strip()
#     for key, tz in CITY_TIMEZONE.items():
#         if key in city_lower:
#             return tz
#     return {"tz_name": "EST", "utc_offset": -5}


# def _format_12h(time_24h: str) -> str:
#     h, m = map(int, time_24h.split(":"))
#     period = "AM" if h < 12 else "PM"
#     h12 = h if 1 <= h <= 12 else (12 if h == 0 else h - 12)
#     return f"{h12}:{m:02d} {period}"


# def _convert_tz(time_24h: str, from_tz: dict, to_tz: dict) -> str:
#     h, m = map(int, time_24h.split(":"))
#     diff = to_tz["utc_offset"] - from_tz["utc_offset"]
#     new_h = (h + diff) % 24
#     return _format_12h(f"{new_h:02d}:{m:02d}")


# def _generate_meeting_link(provider_name: str) -> str:
#     slug = (provider_name.lower()
#             .replace("dr. ", "dr-").replace("dr ", "dr-")
#             .replace(" ", "-").replace(".", "").replace(",", ""))
#     return f"https://medilife.health/meet/{slug}"


# def _generate_calendar(npi: str, provider_name: str, city: str,
#                         consultation_mode: str, date_str: str = "") -> dict:
#     # Always normalize to ISO format for consistent cache key
#     iso = _resolve_date(date_str) if date_str else datetime.now().strftime("%Y-%m-%d")
#     cache_key = f"{npi}_{iso}"

#     if cache_key in _calendar_cache:
#         cal = _calendar_cache[cache_key]
#     else:
#         seed = int(hashlib.md5(f"{npi}_{iso}".encode()).hexdigest()[:8], 16)
#         rng  = random.Random(seed)

#         shift_name = rng.choice(list(SHIFT_TYPES.keys()))
#         shift      = SHIFT_TYPES[shift_name]
#         tz         = _get_timezone(city)
#         link       = _generate_meeting_link(provider_name) if consultation_mode in ("Telehealth", "Both") else None

#         sh, sm = map(int, shift["start"].split(":"))
#         eh, em = map(int, shift["end"].split(":"))
#         slots  = {}
#         cur    = datetime.now().replace(hour=sh, minute=sm, second=0, microsecond=0)
#         end    = datetime.now().replace(hour=eh, minute=em, second=0, microsecond=0)
#         while cur < end:
#             t = cur.strftime("%H:%M")
#             if rng.random() < 0.4:
#                 slots[t] = {"status": "booked"}
#             else:
#                 slots[t] = {"status": "available"}
#             cur += timedelta(minutes=30)

#         cal = {
#             "shift_name": shift_name, "shift": shift, "tz": tz,
#             "link": link, "slots": slots, "iso_date": iso,
#         }
#         _calendar_cache[cache_key] = cal

#     # Apply persisted real bookings
#     for t in _booked_store.get(f"{npi}_{iso}", []):
#         if t in cal["slots"]:
#             cal["slots"][t] = {"status": "booked"}

#     return cal


# def _parse_time(raw: str) -> str | None:
#     """Parse any reasonable time string to HH:MM (24h)."""
#     s = raw.strip().upper()
#     for sfx in ("PST", "EST", "CST", "MST", "PDT", "EDT", "CDT", "MDT", "UTC"):
#         s = s.replace(sfx, "").strip()

#     if "AM" in s or "PM" in s:
#         is_pm = "PM" in s
#         s = s.replace("AM", "").replace("PM", "").strip()
#         parts = s.replace(".", ":").split(":")
#         try:
#             h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
#             if is_pm and h != 12: h += 12
#             elif not is_pm and h == 12: h = 0
#             return f"{h:02d}:{m:02d}"
#         except (ValueError, IndexError):
#             return None

#     parts = s.replace(".", ":").split(":")
#     try:
#         if len(parts) == 2:
#             return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
#         if len(parts) == 1:
#             return f"{int(parts[0]):02d}:00"
#     except ValueError:
#         pass
#     return None


# def _resolve_date(appointment_date: str) -> str:
#     """Resolve 'today', 'tomorrow', or date strings to YYYY-MM-DD."""
#     if not appointment_date:
#         return ""
#     d = appointment_date.strip().lower()
#     today = datetime.now().date()
#     if d == "today":
#         return today.strftime("%Y-%m-%d")
#     if d == "tomorrow":
#         return (today + timedelta(days=1)).strftime("%Y-%m-%d")
#     import re
#     resolved = None
#     try:
#         cleaned = re.sub(r'^[A-Za-z]+,\s*', '', appointment_date.strip())
#         resolved = datetime.strptime(cleaned, "%B %d, %Y").date()
#     except ValueError:
#         pass
#     if resolved is None:
#         for fmt in ("%Y-%m-%d", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
#             try:
#                 resolved = datetime.strptime(appointment_date.strip(), fmt).date()
#                 break
#             except ValueError:
#                 pass
#     if resolved is None:
#         return appointment_date
#     if resolved < today:
#         resolved = today + timedelta(days=1)
#     return resolved.strftime("%Y-%m-%d")


# # ── Public API ────────────────────────────────────────────────────────────────

# def check_provider_availability(
#     npi: str,
#     provider_name: str,
#     city: str,
#     consultation_mode: str = "Both",
#     appointment_date: str = "",
# ) -> dict:
#     today    = datetime.now().date()
#     now_time = datetime.now().strftime("%H:%M")

#     # Resolve the requested start date (default = today)
#     iso_date = _resolve_date(appointment_date)
#     try:
#         start_date = datetime.strptime(iso_date, "%Y-%m-%d").date() if iso_date else today
#     except ValueError:
#         start_date = today

#     # Auto-advance: try up to 7 days ahead to find a date with available slots
#     for offset in range(8):
#         check_date = start_date + timedelta(days=offset)
#         iso_check  = check_date.strftime("%Y-%m-%d")
#         cal        = _generate_calendar(npi, provider_name, city, consultation_mode, iso_check)

#         available = []
#         for t, slot in sorted(cal["slots"].items()):
#             if check_date == today and t <= now_time:
#                 continue
#             if slot["status"] == "available":
#                 available.append({"time_24h": t, "time_display": _format_12h(t)})

#         if available:
#             # Found a day with open slots — return it
#             skipped_note = ""
#             if offset > 0 and (not appointment_date or appointment_date.strip().lower() in ("", "today")):
#                 skipped_note = f"No slots available today — showing next available: {check_date.strftime('%A, %B %d, %Y')}."
#             elif offset > 1:
#                 skipped_note = f"No slots on {start_date.strftime('%B %d')} — showing next available: {check_date.strftime('%A, %B %d, %Y')}."

#             return {
#                 "npi":                  npi,
#                 "provider_name":        provider_name,
#                 "date":                 check_date.strftime("%B %d, %Y"),
#                 "date_iso":             iso_check,
#                 "shift":                cal["shift_name"],
#                 "shift_hours":          f"{_format_12h(cal['shift']['start'])} – {_format_12h(cal['shift']['end'])}",
#                 "timezone":             cal["tz"]["tz_name"],
#                 "consultation_mode":    consultation_mode,
#                 "telehealth_link":      cal["link"],
#                 "available_slot_count": len(available),
#                 "available_slots":      available,
#                 "skipped_note":         skipped_note,
#             }

#     # No availability in the next 7 days
#     return {
#         "npi":                  npi,
#         "provider_name":        provider_name,
#         "date":                 start_date.strftime("%B %d, %Y"),
#         "available_slot_count": 0,
#         "available_slots":      [],
#         "message":              f"No available slots for {provider_name} in the next 7 days. Please try a different provider.",
#     }


# def get_urgent_slots(
#     npi: str,
#     provider_name: str,
#     city: str,
#     consultation_mode: str = "Both",
# ) -> dict:
#     now      = datetime.now()
#     iso_date = now.strftime("%Y-%m-%d")
#     cal      = _generate_calendar(npi, provider_name, city, consultation_mode, iso_date)
#     now_time = now.strftime("%H:%M")

#     remaining = [
#         {"time_24h": t, "time_display": _format_12h(t)}
#         for t, s in sorted(cal["slots"].items())
#         if t > now_time and s["status"] == "available"
#     ]

#     return {
#         "npi":              npi,
#         "provider_name":    provider_name,
#         "date":             now.strftime("%B %d, %Y"),
#         "timezone":         cal["tz"]["tz_name"],
#         "shift_hours":      f"{_format_12h(cal['shift']['start'])} – {_format_12h(cal['shift']['end'])}",
#         "consultation_mode": consultation_mode,
#         "telehealth_link":  cal["link"],
#         "remaining_today":  len(remaining),
#         "available_slots":  remaining,
#         "urgent":           True,
#     }


# def book_provider_appointment(
#     npi: str,
#     provider_name: str,
#     city: str,
#     time_slot: str,
#     consultation_type: str,
#     consultation_mode: str = "Both",
#     member_city: str = "",
#     appointment_date: str = "",
#     member_id: str = "",
# ) -> dict:
#     iso_date = _resolve_date(appointment_date)
#     cal      = _generate_calendar(npi, provider_name, city, consultation_mode, iso_date)
#     parsed   = _parse_time(time_slot)

#     if not parsed:
#         return {"status": "error", "message": f"Could not understand time '{time_slot}'. Use format like '10:30 AM'."}

#     if consultation_type == "Telehealth" and consultation_mode == "In-Person":
#         return {"status": "error", "message": f"{provider_name} only offers In-Person visits."}
#     if consultation_type == "In-Person" and consultation_mode == "Telehealth":
#         return {"status": "error", "message": f"{provider_name} only offers Telehealth visits."}

#     if parsed not in cal["slots"]:
#         shift = cal["shift"]
#         return {
#             "status": "error",
#             "message": (f"{_format_12h(parsed)} is outside {provider_name}'s hours "
#                         f"({_format_12h(shift['start'])} – {_format_12h(shift['end'])} "
#                         f"{cal['tz']['tz_name']}). Please choose a time within these hours."),
#         }

#     if cal["slots"][parsed]["status"] == "booked":
#         # Check if this member already owns this slot (telehealth conversion of existing booking)
#         member_owns_slot = False
#         if member_id:
#             try:
#                 from app.services.storage_service import storage
#                 existing = storage.get_bookings(member_id)
#                 for b in existing:
#                     b_time = _parse_time(b.get("time_start", ""))
#                     b_iso  = _resolve_date(b.get("date", ""))
#                     if b.get("npi") == npi and b_time == parsed and b_iso == iso_date:
#                         member_owns_slot = True
#                         break
#             except Exception:
#                 pass

#         if not member_owns_slot:
#             nearest = sorted(
#                 [t for t, s in cal["slots"].items() if s["status"] == "available"],
#                 key=lambda t: abs(
#                     int(t.split(":")[0]) * 60 + int(t.split(":")[1]) -
#                     int(parsed.split(":")[0]) * 60 - int(parsed.split(":")[1])
#                 )
#             )[:3]
#             return {
#                 "status":           "unavailable",
#                 "message":          f"Sorry, {_format_12h(parsed)} is already booked.",
#                 "nearest_available": [_format_12h(t) for t in nearest],
#                 "suggestion":       f"Nearest available: {', '.join(_format_12h(t) for t in nearest)}. Which would you prefer?",
#             }
#         # Member owns this slot — allow rebooking (telehealth conversion)

#     # Book it
#     cal["slots"][parsed] = {"status": "booked"}
#     iso_date = cal.get("iso_date", iso_date)  # use the normalized date from calendar
#     persist_key = f"{npi}_{iso_date}"
#     _booked_store.setdefault(persist_key, [])
#     if parsed not in _booked_store[persist_key]:
#         _booked_store[persist_key].append(parsed)
#     _save_appointments(_booked_store)

#     # Compute end time
#     h, m   = map(int, parsed.split(":"))
#     end_h  = h + (1 if m + 30 >= 60 else 0)
#     end_m  = (m + 30) % 60
#     end_t  = f"{end_h:02d}:{end_m:02d}"

#     provider_tz = cal["tz"]
#     member_tz   = _get_timezone(member_city) if member_city else provider_tz

#     booking = {
#         "status":           "confirmed",
#         "provider_name":    provider_name,
#         "npi":              npi,
#         "date":             datetime.strptime(iso_date, "%Y-%m-%d").strftime("%B %d, %Y") if iso_date else datetime.now().strftime("%B %d, %Y"),
#         "time_start":       _format_12h(parsed),
#         "time_end":         _format_12h(end_t),
#         "timezone":         provider_tz["tz_name"],
#         "consultation_type": consultation_type,
#     }

#     if member_tz["tz_name"] != provider_tz["tz_name"]:
#         booking["member_time"]    = f"{_convert_tz(parsed, provider_tz, member_tz)} – {_convert_tz(end_t, provider_tz, member_tz)} {member_tz['tz_name']}"
#         booking["timezone_note"]  = f"That's {_convert_tz(parsed, provider_tz, member_tz)} your time ({member_tz['tz_name']})"

#     if consultation_type == "Telehealth" and cal["link"]:
#         booking["telehealth_link"] = cal["link"]
#     if consultation_type == "In-Person":
#         booking["visit_note"] = "Please arrive 15 minutes early for check-in."

#     # Persist to member appointments log
#     if member_id:
#         _persist_member_appointment(member_id, booking)
#         # Also save to StorageService for cross-session memory
#         try:
#             from app.services.storage_service import storage
#             storage.save_booking(member_id, booking)
#         except Exception:
#             pass

#     return booking


# def _persist_member_appointment(member_id: str, booking: dict):
#     """Append confirmed booking to member's conversation log for memory."""
#     log_dir  = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "conversation", "txt")
#     os.makedirs(log_dir, exist_ok=True)
#     log_file = os.path.join(log_dir, f"{member_id}_appointments.txt")
#     line = (
#         f"[{datetime.now().strftime('%H:%M:%S')}] BOOKING CONFIRMED: "
#         f"Your {booking['consultation_type']} appointment with {booking['provider_name']} "
#         f"on {booking['date']}, from {booking['time_start']} {booking['timezone']}\n"
#     )
#     with open(log_file, "a", encoding="utf-8") as f:
#         f.write(line)

"""
Calendar Service — timezone-aware appointment scheduling.
Generates deterministic mock calendars per provider+date (NPI-seeded).
Persists real bookings to appointments.json so they survive restarts.
"""
 
import hashlib
import json
import os
import random
from datetime import datetime, timedelta
 
# ── Timezone map ──────────────────────────────────────────────────────────────
CITY_TIMEZONE = {
    "los angeles": {"tz_name": "PST", "utc_offset": -8},
    "new york":    {"tz_name": "EST", "utc_offset": -5},
    "miami":       {"tz_name": "EST", "utc_offset": -5},
    "chicago":     {"tz_name": "CST", "utc_offset": -6},
    "houston":     {"tz_name": "CST", "utc_offset": -6},
    "seattle":     {"tz_name": "PST", "utc_offset": -8},
    "dallas":      {"tz_name": "CST", "utc_offset": -6},
    "austin":      {"tz_name": "CST", "utc_offset": -6},
}
 
SHIFT_TYPES = {
    "Standard": {"start": "08:00", "end": "17:00"},
}
 
SAME_DAY_CUTOFF = "15:00"  # No same-day bookings after 3 PM
 
_APPOINTMENTS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "logs", "appointments.json"
)
_calendar_cache: dict = {}
 
 
# ── Persistence ───────────────────────────────────────────────────────────────
 
def _load_appointments() -> dict:
    try:
        if os.path.exists(_APPOINTMENTS_FILE):
            with open(_APPOINTMENTS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}
 
 
def _save_appointments(data: dict):
    os.makedirs(os.path.dirname(_APPOINTMENTS_FILE), exist_ok=True)
    try:
        with open(_APPOINTMENTS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
 
 
_booked_store: dict = _load_appointments()
_calendar_cache: dict = {}  # cleared on every server start — fresh calendars each session
 
 
# ── Helpers ───────────────────────────────────────────────────────────────────
 
def _get_timezone(city: str) -> dict:
    city_lower = city.lower().strip()
    for key, tz in CITY_TIMEZONE.items():
        if key in city_lower:
            return tz
    return {"tz_name": "EST", "utc_offset": -5}
 
 
def _format_12h(time_24h: str) -> str:
    h, m = map(int, time_24h.split(":"))
    period = "AM" if h < 12 else "PM"
    h12 = h if 1 <= h <= 12 else (12 if h == 0 else h - 12)
    return f"{h12}:{m:02d} {period}"
 
 
def _convert_tz(time_24h: str, from_tz: dict, to_tz: dict) -> str:
    h, m = map(int, time_24h.split(":"))
    diff = to_tz["utc_offset"] - from_tz["utc_offset"]
    new_h = (h + diff) % 24
    return _format_12h(f"{new_h:02d}:{m:02d}")
 
 
def _relative_date_label(check_date, today) -> str:
    delta = (check_date - today).days
    if delta == 0:
        return "today, "
    if delta == 1:
        return "tomorrow, "
    if delta == 2:
        return "in 2 days, "
    if 3 <= delta <= 6:
        return f"this {check_date.strftime('%A')}, "
    if delta == 7:
        return f"next {check_date.strftime('%A')}, "
    return ""
 
 
def _generate_meeting_link(provider_name: str) -> str:
    slug = (provider_name.lower()
            .replace("dr. ", "dr-").replace("dr ", "dr-")
            .replace(" ", "-").replace(".", "").replace(",", ""))
    return f"https://medilife.health/meet/{slug}"
 
 
def _generate_calendar(npi: str, provider_name: str, city: str,
                        consultation_mode: str, date_str: str = "") -> dict:
    # Always normalize to ISO format for consistent cache key
    iso = _resolve_date(date_str) if date_str else datetime.now().strftime("%Y-%m-%d")
    cache_key = f"{npi}_{iso}"
 
    if cache_key in _calendar_cache:
        cal = _calendar_cache[cache_key]
    else:
        seed = int(hashlib.md5(f"{npi}_{iso}".encode()).hexdigest()[:8], 16)
        rng  = random.Random(seed)
 
        shift_name = "Standard"
        shift      = SHIFT_TYPES["Standard"]
        tz         = _get_timezone(city)
        link       = _generate_meeting_link(provider_name) if consultation_mode in ("Telehealth", "Both") else None
 
        sh, sm = map(int, shift["start"].split(":"))
        eh, em = map(int, shift["end"].split(":"))
        slots  = {}
        cur    = datetime.now().replace(hour=sh, minute=sm, second=0, microsecond=0)
        end    = datetime.now().replace(hour=eh, minute=em, second=0, microsecond=0)
        while cur < end:
            t = cur.strftime("%H:%M")
            if rng.random() < 0.4:
                slots[t] = {"status": "booked"}
            else:
                slots[t] = {"status": "available"}
            cur += timedelta(minutes=30)
 
        cal = {
            "shift_name": shift_name, "shift": shift, "tz": tz,
            "link": link, "slots": slots, "iso_date": iso,
        }
        _calendar_cache[cache_key] = cal
 
    # Apply persisted real bookings
    for t in _booked_store.get(f"{npi}_{iso}", []):
        if t in cal["slots"]:
            cal["slots"][t] = {"status": "booked"}
 
    return cal
 
 
def _parse_time(raw: str) -> str | None:
    """Parse any reasonable time string to HH:MM (24h)."""
    s = raw.strip().upper()
    for sfx in ("PST", "EST", "CST", "MST", "PDT", "EDT", "CDT", "MDT", "UTC"):
        s = s.replace(sfx, "").strip()
 
    if "AM" in s or "PM" in s:
        is_pm = "PM" in s
        s = s.replace("AM", "").replace("PM", "").strip()
        parts = s.replace(".", ":").split(":")
        try:
            h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            if is_pm and h != 12: h += 12
            elif not is_pm and h == 12: h = 0
            return f"{h:02d}:{m:02d}"
        except (ValueError, IndexError):
            return None
 
    parts = s.replace(".", ":").split(":")
    try:
        if len(parts) == 2:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        if len(parts) == 1:
            return f"{int(parts[0]):02d}:00"
    except ValueError:
        pass
    return None
 
 
def _resolve_date(appointment_date: str) -> str:
    """Resolve 'today', 'tomorrow', or date strings to YYYY-MM-DD."""
    if not appointment_date:
        return ""
    d = appointment_date.strip().lower()
    today = datetime.now().date()
    if d == "today":
        return today.strftime("%Y-%m-%d")
    if d == "tomorrow":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    import re
    resolved = None
    try:
        cleaned = re.sub(r'^[A-Za-z]+,\s*', '', appointment_date.strip())
        resolved = datetime.strptime(cleaned, "%B %d, %Y").date()
    except ValueError:
        pass
    if resolved is None:
        for fmt in ("%Y-%m-%d", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
            try:
                resolved = datetime.strptime(appointment_date.strip(), fmt).date()
                break
            except ValueError:
                pass
    if resolved is None:
        return appointment_date
    if resolved < today:
        resolved = today + timedelta(days=1)
    return resolved.strftime("%Y-%m-%d")
 
 
# ── Public API ────────────────────────────────────────────────────────────────
 
def check_provider_availability(
    npi: str,
    provider_name: str,
    city: str,
    consultation_mode: str = "Both",
    appointment_date: str = "",
    client_time: str = "",   # "HH:MM" from browser local time
    client_date: str = "",   # "YYYY-MM-DD" from browser local date
    no_advance: bool = False, # if True, show the exact requested date (don't auto-jump to next available)
) -> dict:
    today    = datetime.now().date()
    now_time = datetime.now().strftime("%H:%M")
 
    # Use browser local time if provided (avoids server UTC mismatch)
    # Apply 2-hour cooldown: cutoff = client_time + 120 min
    if client_time and client_date:
        try:
            _ch, _cm = map(int, client_time[:5].split(":"))
            _cutoff_total = _ch * 60 + _cm + 120
            _cutoff_h = (_cutoff_total // 60) % 24
            _cutoff_m = _cutoff_total % 60
            now_time = f"{_cutoff_h:02d}:{_cutoff_m:02d}"
            today = datetime.strptime(client_date, "%Y-%m-%d").date()
        except Exception:
            pass
    else:
        # Server-side fallback: apply 2-hour buffer to server time
        _now = datetime.now()
        _cutoff = _now + timedelta(hours=2)
        now_time = _cutoff.strftime("%H:%M")
 
    # Resolve the requested start date (default = today)
    iso_date = _resolve_date(appointment_date)
    try:
        start_date = datetime.strptime(iso_date, "%Y-%m-%d").date() if iso_date else today
    except ValueError:
        start_date = today
 
    # When no_advance=True (modal explicitly selected a date), show that exact date
    # with past slots greyed — don't skip to the next available day.
    if no_advance:
        check_date = start_date
        iso_check  = check_date.strftime("%Y-%m-%d")
        cal        = _generate_calendar(npi, provider_name, city, consultation_mode, iso_check)
        all_day_slots = []
        available = []
        for t, slot in sorted(cal["slots"].items()):
            is_past   = (check_date == today and (t <= now_time or now_time >= SAME_DAY_CUTOFF))
            is_booked = (slot["status"] == "booked")
            all_day_slots.append({
                "time_24h":     t,
                "time_display": _format_12h(t),
                "past":         is_past,
                "booked":       is_booked,
            })
            if not is_past and not is_booked:
                available.append({"time_24h": t, "time_display": _format_12h(t)})
        return {
            "npi":                  npi,
            "provider_name":        provider_name,
            "date":                 _relative_date_label(check_date, today) + check_date.strftime("%A, %b %d"),
            "date_iso":             iso_check,
            "shift":                cal["shift_name"],
            "shift_hours":          f"{_format_12h(cal['shift']['start'])} \u2013 {_format_12h(cal['shift']['end'])}",
            "timezone":             cal["tz"]["tz_name"],
            "consultation_mode":    consultation_mode,
            "telehealth_link":      cal["link"],
            "available_slot_count": len(available),
            "available_slots":      available,
            "all_day_slots":        all_day_slots,
            "skipped_note":         "",
        }
 
    # Auto-advance: try up to 7 days ahead to find a date with available slots
    for offset in range(8):
        check_date = start_date + timedelta(days=offset)
        iso_check  = check_date.strftime("%Y-%m-%d")
        cal        = _generate_calendar(npi, provider_name, city, consultation_mode, iso_check)
 
        # Build full slot list — all slots from 8am to 5pm
        # Each slot is either: past (before cutoff), booked (40% random), or available
        all_day_slots = []
        available = []
        for t, slot in sorted(cal["slots"].items()):
            is_past   = (check_date == today and (t <= now_time or now_time >= SAME_DAY_CUTOFF))
            is_booked = (slot["status"] == "booked")
            all_day_slots.append({
                "time_24h":    t,
                "time_display": _format_12h(t),
                "past":        is_past,
                "booked":      is_booked,
            })
            if not is_past and not is_booked:
                available.append({"time_24h": t, "time_display": _format_12h(t)})
 
        if available:
            # Found a day with open slots — return it
            skipped_note = ""
            if offset > 0 and (not appointment_date or appointment_date.strip().lower() in ("", "today")):
                skipped_note = f"No slots available today — showing next available: {check_date.strftime('%A, %B %d, %Y')}."
            elif offset > 1:
                skipped_note = f"No slots on {start_date.strftime('%B %d')} — showing next available: {check_date.strftime('%A, %B %d, %Y')}."
 
            return {
                "npi":                  npi,
                "provider_name":        provider_name,
                "date":                 _relative_date_label(check_date, today) + check_date.strftime("%A, %b %d"),
                "date_iso":             iso_check,
                "shift":                cal["shift_name"],
                "shift_hours":          f"{_format_12h(cal['shift']['start'])} – {_format_12h(cal['shift']['end'])}",
                "timezone":             cal["tz"]["tz_name"],
                "consultation_mode":    consultation_mode,
                "telehealth_link":      cal["link"],
                "available_slot_count": len(available),
                "available_slots":      available,
                "all_day_slots":        all_day_slots,
                "skipped_note":         skipped_note,
            }
 
    # No availability in the next 7 days
    return {
        "npi":                  npi,
        "provider_name":        provider_name,
        "date":                 start_date.strftime("%B %d, %Y"),
        "available_slot_count": 0,
        "available_slots":      [],
        "message":              f"No available slots for {provider_name} in the next 7 days. Please try a different provider.",
    }
 
 
def get_urgent_slots(
    npi: str,
    provider_name: str,
    city: str,
    consultation_mode: str = "Both",
    client_time: str = "",
    client_date: str = "",
) -> dict:
    now      = datetime.now()
    iso_date = now.strftime("%Y-%m-%d")
 
    # Use browser local time if provided (same logic as check_provider_availability)
    if client_time and client_date:
        try:
            _ch, _cm = map(int, client_time[:5].split(":"))
            _cutoff_total = _ch * 60 + _cm + 120
            _cutoff_h = (_cutoff_total // 60) % 24
            _cutoff_m = _cutoff_total % 60
            now_time = f"{_cutoff_h:02d}:{_cutoff_m:02d}"
            iso_date = client_date
        except Exception:
            cutoff   = now + timedelta(hours=2)
            now_time = cutoff.strftime("%H:%M")
    else:
        cutoff   = now + timedelta(hours=2)
        now_time = cutoff.strftime("%H:%M")
 
    cal = _generate_calendar(npi, provider_name, city, consultation_mode, iso_date)
 
    remaining = [
        {"time_24h": t, "time_display": _format_12h(t)}
        for t, s in sorted(cal["slots"].items())
        if t > now_time and s["status"] == "available"
    ]
 
    return {
        "npi":              npi,
        "provider_name":    provider_name,
        "date":             now.strftime("%B %d, %Y"),
        "timezone":         cal["tz"]["tz_name"],
        "shift_hours":      f"{_format_12h(cal['shift']['start'])} – {_format_12h(cal['shift']['end'])}",
        "consultation_mode": consultation_mode,
        "telehealth_link":  cal["link"],
        "remaining_today":  len(remaining),
        "available_slots":  remaining,
        "urgent":           True,
    }
 
 
def book_provider_appointment(
    npi: str,
    provider_name: str,
    city: str,
    time_slot: str,
    consultation_type: str,
    consultation_mode: str = "Both",
    member_city: str = "",
    appointment_date: str = "",
    member_id: str = "",
    reason: str = "",
) -> dict:
    iso_date = _resolve_date(appointment_date)
    parsed   = _parse_time(time_slot)
 
    if not parsed:
        return {"status": "error", "message": f"Could not understand time '{time_slot}'. Use format like '10:30 AM'."}

    # ── Telehealth or In-Person conversion fast-path ───────────────────────────
    # If the member already owns this exact slot in storage (same npi + date + time),
    # bypass the calendar entirely — the slot is pre-confirmed.
    # This handles location-change conversions and reversals (Telehealth <-> In-Person)
    # where the booking was saved directly to storage (not through the calendar service)
    # and ensures database consistency.
    if member_id and consultation_type in ("Telehealth", "In-Person"):
        try:
            from app.services.storage_service import storage as _storage
            # Check both bookings AND appointments files — frontend saves to appointments,
            # storage service saves to bookings. Must check both to handle all cases.
            _all_existing = list(_storage.get_bookings(member_id))
            _appts_file = _storage.read(f"appointments/{member_id}.json") or []
            _seen_keys = {f"{b.get('npi')}|{_resolve_date(b.get('date',''))}" for b in _all_existing}
            for _a in _appts_file:
                _k = f"{_a.get('npi', _a.get('npi', ''))}|{_resolve_date(_a.get('date',''))}"
                if _k not in _seen_keys:
                    _all_existing.append(_a)
            for b in _all_existing:
                if (
                    b.get("npi") == npi
                    and _parse_time(b.get("time_start", "")) == parsed
                    and _resolve_date(b.get("date", "")) == iso_date
                ):
                    # Member owns this slot — update in storage and return confirmed
                    # Update bookings file
                    bookings = _storage.get_bookings(member_id)
                    _updated_bookings = False
                    for bk in bookings:
                        if (
                            bk.get("npi") == npi
                            and _parse_time(bk.get("time_start", "")) == parsed
                            and _resolve_date(bk.get("date", "")) == iso_date
                        ):
                            bk["consultation_type"] = consultation_type
                            if consultation_type == "Telehealth":
                                bk["telehealth_link"] = _generate_meeting_link(provider_name)
                                bk.pop("visit_note", None)
                            else:
                                bk["visit_note"] = "Please arrive 15 minutes early for check-in."
                                bk.pop("telehealth_link", None)
                            if reason:
                                bk["reason"] = reason
                            _updated_bookings = True
                            break
                    if _updated_bookings:
                        _storage.write(f"bookings/{member_id}.json", bookings)
                    # Also update appointments file if that's where it was found
                    appts = _storage.read(f"appointments/{member_id}.json") or []
                    for bk in appts:
                        _bk_npi = bk.get("npi", "")
                        _bk_name = bk.get("provider_name", bk.get("provider", ""))
                        if (
                            (_bk_npi == npi or _bk_name.upper() == provider_name.upper())
                            and _parse_time(bk.get("time_start", "")) == parsed
                            and _resolve_date(bk.get("date", "")) == iso_date
                        ):
                            bk["consultation_type"] = consultation_type
                            if consultation_type == "Telehealth":
                                bk["telehealth_link"] = _generate_meeting_link(provider_name)
                                bk.pop("visit_note", None)
                            else:
                                bk["visit_note"] = "Please arrive 15 minutes early for check-in."
                                bk.pop("telehealth_link", None)
                            if reason:
                                bk["reason"] = reason
                            # Ensure NPI is set for future lookups
                            if not _bk_npi and npi:
                                bk["npi"] = npi
                            break
                    _storage.write(f"appointments/{member_id}.json", appts)
                    provider_tz = _get_timezone(city)
                    member_tz   = _get_timezone(member_city) if member_city else provider_tz
                    h, m   = map(int, parsed.split(":"))
                    end_h  = (h * 60 + m + 60) // 60
                    end_m  = (m + 60) % 60
                    end_t  = f"{end_h:02d}:{end_m:02d}"
                    converted = {
                        "status":            "confirmed",
                        "provider_name":     provider_name,
                        "npi":               npi,
                        "date":              datetime.strptime(iso_date, "%Y-%m-%d").strftime("%B %d, %Y") if iso_date else datetime.now().strftime("%B %d, %Y"),
                        "time_start":        _format_12h(parsed),
                        "time_end":          _format_12h(end_t),
                        "timezone":          provider_tz["tz_name"],
                        "consultation_type": consultation_type,
                        "reason":            reason,
                    }
                    if consultation_type == "Telehealth":
                        converted["telehealth_link"] = _generate_meeting_link(provider_name)
                    else:
                        converted["visit_note"] = "Please arrive 15 minutes early for check-in."
                    if member_tz["tz_name"] != provider_tz["tz_name"]:
                        converted["member_time"]   = f"{_convert_tz(parsed, provider_tz, member_tz)} – {_convert_tz(end_t, provider_tz, member_tz)} {member_tz['tz_name']}"
                        converted["timezone_note"] = f"That's {_convert_tz(parsed, provider_tz, member_tz)} your time ({member_tz['tz_name']})"
                    _persist_member_appointment(member_id, converted)
                    return converted
        except Exception:
            pass

    cal = _generate_calendar(npi, provider_name, city, consultation_mode, iso_date)
 
    if consultation_type == "Telehealth" and consultation_mode == "In-Person":
        return {"status": "error", "message": f"{provider_name} only offers In-Person visits."}
    if consultation_type == "In-Person" and consultation_mode == "Telehealth":
        return {"status": "error", "message": f"{provider_name} only offers Telehealth visits."}
 
    if parsed not in cal["slots"]:
        shift = cal["shift"]
        return {
            "status": "error",
            "message": (f"{_format_12h(parsed)} is outside {provider_name}'s hours "
                        f"({_format_12h(shift['start'])} – {_format_12h(shift['end'])} "
                        f"{cal['tz']['tz_name']}). Please choose a time within these hours."),
        }
 
    if cal["slots"][parsed]["status"] == "booked":
        # Allow rebooking if the member already owns this exact slot
        # (e.g. converting an In-Person appointment to Telehealth)
        member_owns_slot = False
        if member_id:
            try:
                from app.services.storage_service import storage as _storage
                for b in _storage.get_bookings(member_id):
                    if (
                        b.get("npi") == npi
                        and _parse_time(b.get("time_start", "")) == parsed
                        and _resolve_date(b.get("date", "")) == iso_date
                    ):
                        member_owns_slot = True
                        break
            except Exception:
                pass

        if not member_owns_slot:
            nearest = sorted(
                [t for t, s in cal["slots"].items() if s["status"] == "available"],
                key=lambda t: abs(
                    int(t.split(":")[0]) * 60 + int(t.split(":")[1]) -
                    int(parsed.split(":")[0]) * 60 - int(parsed.split(":")[1])
                )
            )[:3]
            return {
                "status":           "unavailable",
                "message":          f"Sorry, {_format_12h(parsed)} is already booked.",
                "nearest_available": [_format_12h(t) for t in nearest],
                "suggestion":       f"Nearest available: {', '.join(_format_12h(t) for t in nearest)}. Which would you prefer?",
            }
        else:
            # Member owns this slot — telehealth conversion.
            # Update consultation_type in storage and return confirmed immediately.
            try:
                from app.services.storage_service import storage as _storage
                bookings = _storage.get_bookings(member_id)
                for bk in bookings:
                    if (
                        bk.get("npi") == npi
                        and _parse_time(bk.get("time_start", "")) == parsed
                        and _resolve_date(bk.get("date", "")) == iso_date
                    ):
                        bk["consultation_type"] = consultation_type
                        if consultation_type == "Telehealth":
                            bk["telehealth_link"] = _generate_meeting_link(provider_name)
                            bk.pop("visit_note", None)
                        else:
                            bk["visit_note"] = "Please arrive 15 minutes early for check-in."
                            bk.pop("telehealth_link", None)
                        if reason:
                            bk["reason"] = reason
                        break
                _storage.write(f"bookings/{member_id}.json", bookings)
                provider_tz = cal["tz"]
                member_tz   = _get_timezone(member_city) if member_city else provider_tz
                h, m   = map(int, parsed.split(":"))
                end_h  = (h * 60 + m + 60) // 60
                end_m  = (m + 60) % 60
                end_t  = f"{end_h:02d}:{end_m:02d}"
                converted = {
                    "status":            "confirmed",
                    "provider_name":     provider_name,
                    "npi":               npi,
                    "date":              datetime.strptime(iso_date, "%Y-%m-%d").strftime("%B %d, %Y"),
                    "time_start":        _format_12h(parsed),
                    "time_end":          _format_12h(end_t),
                    "timezone":          provider_tz["tz_name"],
                    "consultation_type": consultation_type,
                    "reason":            reason,
                }
                if consultation_type == "Telehealth":
                    converted["telehealth_link"] = _generate_meeting_link(provider_name)
                if member_tz["tz_name"] != provider_tz["tz_name"]:
                    converted["member_time"]   = f"{_convert_tz(parsed, provider_tz, member_tz)} – {_convert_tz(end_t, provider_tz, member_tz)} {member_tz['tz_name']}"
                    converted["timezone_note"] = f"That's {_convert_tz(parsed, provider_tz, member_tz)} your time ({member_tz['tz_name']})"
                return converted
            except Exception:
                pass  # fall through to normal booking if update fails

    # ── Member-level conflict check ───────────────────────────────────────────
    # Prevent double-booking: a member cannot have two appointments at the same
    # date + time, even with different providers (different provider calendars
    # are independent and would not catch this on their own).
    if member_id:
        try:
            from app.services.storage_service import storage as _storage
            existing_bookings = _storage.get_bookings(member_id)
            for existing in existing_bookings:
                existing_parsed = _parse_time(existing.get("time_start", ""))
                existing_iso    = _resolve_date(existing.get("date", ""))
                # Same date + same time + different provider = conflict
                if (
                    existing_iso == iso_date
                    and existing_parsed == parsed
                    and existing.get("npi") != npi
                ):
                    conflicting_provider = existing.get("provider_name", "another provider")
                    return {
                        "status":  "conflict",
                        "message": (
                            f"You already have an appointment with {conflicting_provider} "
                            f"at {_format_12h(parsed)} on "
                            f"{datetime.strptime(iso_date, '%Y-%m-%d').strftime('%B %d, %Y')}. "
                            f"Please choose a different time slot for {provider_name}."
                        ),
                        "conflicting_provider": conflicting_provider,
                        "conflicting_time":      _format_12h(parsed),
                    }
        except Exception:
            pass

    # Book it
    cal["slots"][parsed] = {"status": "booked"}
    iso_date = cal.get("iso_date", iso_date)  # use the normalized date from calendar
    persist_key = f"{npi}_{iso_date}"
    _booked_store.setdefault(persist_key, [])
    if parsed not in _booked_store[persist_key]:
        _booked_store[persist_key].append(parsed)
    _save_appointments(_booked_store)
 
    # Compute end time (1-hour appointment duration)
    h, m   = map(int, parsed.split(":"))
    end_h  = (h * 60 + m + 60) // 60
    end_m  = (m + 60) % 60
    end_t  = f"{end_h:02d}:{end_m:02d}"
 
    provider_tz = cal["tz"]
    member_tz   = _get_timezone(member_city) if member_city else provider_tz
 
    booking = {
        "status":           "confirmed",
        "provider_name":    provider_name,
        "npi":              npi,
        "date":             datetime.strptime(iso_date, "%Y-%m-%d").strftime("%B %d, %Y") if iso_date else datetime.now().strftime("%B %d, %Y"),
        "time_start":       _format_12h(parsed),
        "time_end":         _format_12h(end_t),
        "timezone":         provider_tz["tz_name"],
        "consultation_type": consultation_type,
        "reason":           reason,
    }
 
    if member_tz["tz_name"] != provider_tz["tz_name"]:
        booking["member_time"]    = f"{_convert_tz(parsed, provider_tz, member_tz)} – {_convert_tz(end_t, provider_tz, member_tz)} {member_tz['tz_name']}"
        booking["timezone_note"]  = f"That's {_convert_tz(parsed, provider_tz, member_tz)} your time ({member_tz['tz_name']})"
 
    if consultation_type == "Telehealth" and cal["link"]:
        booking["telehealth_link"] = cal["link"]
    if consultation_type == "In-Person":
        booking["visit_note"] = "Please arrive 15 minutes early for check-in."
 
    # Persist to member appointments log
    if member_id:
        _persist_member_appointment(member_id, booking)
        # Also save to StorageService for cross-session memory
        try:
            from app.services.storage_service import storage
            storage.save_booking(member_id, booking)
        except Exception:
            pass
 
    return booking
 
 
def _persist_member_appointment(member_id: str, booking: dict):
    """Append confirmed booking to member's conversation log for memory."""
    log_dir  = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "conversation", "txt")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{member_id}_appointments.txt")
    line = (
        f"[{datetime.now().strftime('%H:%M:%S')}] BOOKING CONFIRMED: "
        f"Your {booking['consultation_type']} appointment with {booking['provider_name']} "
        f"on {booking['date']}, from {booking['time_start']} {booking['timezone']}\n"
    )
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line)
 