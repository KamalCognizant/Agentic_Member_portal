"""
Provider Search Agent — Google ADK + Vertex AI
Clean architecture: ADK is the only orchestrator.
No sub-agent LLM calls. All tools are pure Python functions.
History and bookings persisted via StorageService (local files or GCS).
"""

import ast
import asyncio
import json
import random
import time as _time
from datetime import datetime
from typing import AsyncIterator

from app.config import settings
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai.types import Content, Part

from app.services.user_service import UserService
from app.services.storage_service import storage
from app.services.calendar_service import (
    check_provider_availability,
    get_urgent_slots,
    book_provider_appointment,
)
from app.services.memory_service import load_member_memory
from app.services.nucc_taxonomy_service import NUCCTaxonomyService
from app.tools.fhir_provider_tool import FHIRProviderTool
from app.tools.nppes_provider_tool import NPPESProviderTool
from app.tools.provider_ranking_tool import ProviderRankingTool
from app.app_logging.audit_logger import audit_logger
import logging

# Module logger for lightweight instrumentation
logger = logging.getLogger(__name__)

# ── Singletons ────────────────────────────────────────────────────────────────
_users        = UserService()
_nucc         = NUCCTaxonomyService()
_fhir_tool    = FHIRProviderTool()
_nppes_tool   = NPPESProviderTool()
_ranking_tool = ProviderRankingTool()
_adk_sessions: dict[str, str]   = {}
_runners:      dict[str, Runner] = {}

# ── Memory cache (avoids re-reading health_memory files on every runner rebuild) ──
_memory_cache: dict[str, tuple[dict, float]] = {}  # user_id → (memory, timestamp)
_MEMORY_CACHE_TTL = 60  # seconds

def _get_cached_memory(user_id: str) -> dict:
    entry = _memory_cache.get(user_id)
    if entry and (_time.time() - entry[1]) < _MEMORY_CACHE_TTL:
        return entry[0]
    mem = load_member_memory(user_id)
    _memory_cache[user_id] = (mem, _time.time())
    return mem

# ── NPPES in-memory cache ─────────────────────────────────────────────────────
_NPPES_CACHE: dict = {}          # key: (specialty, city, state, limit) → (results, timestamp)
_NPPES_CACHE_TTL  = 3600         # seconds — 1 hour TTL

def _nppes_search_cached(specialty: str, city: str, state: str, limit: int = 20) -> list:
    """Return NPPES results from cache when available, else call the API and cache the result."""
    cache_key = (specialty.lower(), city.lower(), state.lower(), limit)
    entry = _NPPES_CACHE.get(cache_key)
    if entry:
        results, ts = entry
        if _time.time() - ts < _NPPES_CACHE_TTL:
            return results
    results = _nppes_tool.search(specialty=specialty, zipcode="", city=city, state=state, limit=limit)
    _NPPES_CACHE[cache_key] = (results, _time.time())
    return results

# ── Proactive-shown guard (prevents double execution per session) ──────────────
_proactive_shown: set[str] = set()  # user_ids where proactive block already fired this session
# ── Plan ID map — used for plan change context injection ─────────────────────
# Values are (plan_id, canonical_display_name) tuples so the bypass path never
# has to reconstruct the properly-cased name from the lowercase key.
_PLAN_ID_MAP = {
    "cigna true choice medicare (ppo)":        ("plan-cigna-gold",       "Cigna True Choice Medicare (PPO)"),
    "cigna true choice access medicare (ppo)": ("plan-bcbs-platinum",    "Cigna True Choice Access Medicare (PPO)"),
    "cigna total care plus (hmo d-snp)":       ("plan-star-gold",        "Cigna Total Care Plus (HMO D-SNP)"),
    "cigna total care (hmo d-snp)":            ("plan-aetna-gold",       "Cigna Total Care (HMO D-SNP)"),
    "cigna preferred medicare (hmo)":          ("plan-united-platinum",  "Cigna Preferred Medicare (HMO)"),
}

# ── Plan rules ────────────────────────────────────────────────────────────────
_PLAN_RULES = {
    "cigna true choice medicare (ppo)": {
        "requires_referral": False, "prior_auth_required": True,
        "deductible": "$0", "oop_max": "$3,400/year",
        "monthly_premium": "$78/month",
        "specialist_copay": "$20", "pcp_copay": "$0", "telehealth_copay": "$0",
        "notes": "No referral needed. Largest network. Telehealth covered at $0. Prior auth required for imaging and surgery.",
    },
    "cigna true choice access medicare (ppo)": {
        "requires_referral": False, "prior_auth_required": True,
        "deductible": "$100", "oop_max": "$4,500/year",
        "monthly_premium": "$42/month",
        "specialist_copay": "$35", "pcp_copay": "$5", "telehealth_copay": "$0",
        "notes": "No referral needed. Broad PPO network. Prior auth required for imaging and surgery.",
    },
    "cigna total care plus (hmo d-snp)": {
        "requires_referral": True, "prior_auth_required": True,
        "deductible": "$0", "oop_max": "$2,000/year",
        "monthly_premium": "$0/month",
        "specialist_copay": "$45", "pcp_copay": "$10", "telehealth_copay": "$0",
        "notes": "PCP referral required for specialists. Prior auth for imaging/surgery.",
    },
    "cigna total care (hmo d-snp)": {
        "requires_referral": True, "prior_auth_required": True,
        "deductible": "$0", "oop_max": "$2,500/year",
        "monthly_premium": "$0/month",
        "specialist_copay": "$50", "pcp_copay": "$10", "telehealth_copay": "$5",
        "notes": "PCP referral required. Prior auth for imaging and surgery.",
    },
    "cigna preferred medicare (hmo)": {
        "requires_referral": True, "prior_auth_required": True,
        "deductible": "$200", "oop_max": "$5,500/year",
        "monthly_premium": "$19/month",
        "specialist_copay": "$55", "pcp_copay": "$15", "telehealth_copay": "$10",
        "notes": "PCP referral required. Smaller network — in-network only. Prior auth for imaging and surgery.",
    },
}

def _get_plan_rules(insurance_plan: str) -> dict:
    return _PLAN_RULES.get(insurance_plan.lower().strip(), {
        "requires_referral": False, "prior_auth_required": True,
        "deductible": "Unknown", "oop_max": "Unknown",
        "specialist_copay": "Unknown", "pcp_copay": "Unknown",
        "telehealth_copay": "Unknown", "notes": "Plan details not available. Prior auth required for imaging and surgery.",
    })


def _has_mri_prescription(mri_rx: dict | None) -> bool:
    """Return True if mri_rx dict represents a real prescription.
    Handles older writes where prescription_mri key may be absent."""
    if not mri_rx:
        return False
    return bool(
        mri_rx.get("prescription_mri")
        or mri_rx.get("body_part")
        or mri_rx.get("prescribed_by")
        or mri_rx.get("procedure")
    )


def _ensure_dr_prefix(name: str | None) -> str:
    """Return a display name with a single 'Dr.' prefix when appropriate.
    If the provided name already starts with 'Dr.' (or 'Dr '), return it unchanged.
    If name is falsy, return 'your doctor'.
    """
    if not name:
        return "your doctor"
    n = str(name).strip()
    nl = n.lower()
    if nl.startswith("dr.") or nl.startswith("dr "):
        return n
    return f"Dr. {n}"


# ── Proactive context builder ─────────────────────────────────────────────────
def _build_proactive_block(user_id: str, first_name: str, dry_run: bool = False, member_state: dict | None = None) -> str:
    """
    Reads all storage files for this member and returns a block that tells
    the agent exactly what pending items exist and what to proactively address
    on the VERY FIRST response of a new session — before the user asks anything.
    Returns empty string if nothing is pending.

    dry_run=True: reads state but does NOT mark any flags as consumed.
    Use this when building the system prompt context (so the real
    __session_start__ call can still see and consume the flags).

    member_state: pre-loaded dict from storage.get_member_state(). If provided,
    no additional file I/O is performed (avoids duplicate reads with _build_system_prompt).
    """
    # Use pre-loaded state if provided, otherwise read from storage
    _st        = member_state or {}
    mri_rx_pre = _st.get("mri_rx")     if _st else None
    pa_pre     = _st.get("prior_auth") if _st else None
    bk_pre     = _st.get("bookings")   if _st else None
    ref_pre    = _st.get("referral")   if _st else None

    items = []

    # ── MRI prescription + prior auth ────────────────────────────────────────
    try:
        mri_rx     = mri_rx_pre if member_state is not None else storage.get_mri_prescription(user_id)
        prior_auth = pa_pre     if member_state is not None else storage.get_prior_auth(user_id)
        bookings   = bk_pre     if member_state is not None else storage.get_bookings(user_id)
        
        # Check if any completed booking has mri_required set to True
        mri_flagged_booking = None
        for b in (bookings or []):
            if b.get("mri_required") and b.get("status") == "completed":
                mri_flagged_booking = b
                break

        # ONLY process the MRI prescription proactive flow if the UI toggle is ON
        # OR if prior auth has moved past "none" (meaning the flow is already in motion)
        pa_status = (prior_auth or {}).get("status", "none")
        if _has_mri_prescription(mri_rx) and (mri_flagged_booking or pa_status != "none"):
            prescribed_by = mri_rx.get("prescribed_by", {})
            doc_name  = prescribed_by.get("name", "your specialist") if isinstance(prescribed_by, dict) else str(prescribed_by)
            body_part = mri_rx.get("body_part") or mri_rx.get("procedure") or "MRI"
            reason    = mri_rx.get("reason", "")
            pa_status = (prior_auth or {}).get("status", "none")
            pa_ref    = (prior_auth or {}).get("auth_reference_number", "")
            pa_date   = (prior_auth or {}).get("submitted_date", "")
            pa_valid  = (prior_auth or {}).get("valid_through", "")

            # ── Cross-reference: is there already an imaging/scan booking? ──
            # Presence of mri_prescription on file = doctor visit already physically happened.
            # The prescription was given by the provider dashboard — doctor visit is DONE.
            # We must NOT treat the upcoming booking as a "go see the doctor" appointment.
            _MRI_KEYWORDS = {"mri", "scan", "imaging", "radiology", "x-ray", "ct", "pet"}
            imaging_booking = None
            for b in bookings:
                b_reason = (b.get("reason") or "").lower()
                b_provider = (b.get("provider_name") or "").lower()
                if any(kw in b_reason or kw in b_provider for kw in _MRI_KEYWORDS):
                    imaging_booking = b
                    break

            if imaging_booking:
                # Doctor visit is DONE. Prescription is on file. Scan is booked.
                # Agent must reflect reality: visit happened, scan scheduled, just track auth.
                scan_provider = imaging_booking.get("provider_name", "the imaging center")
                scan_date     = imaging_booking.get("date", "")
                scan_time     = imaging_booking.get("time_start", "")
                scan_when     = f"{scan_date} at {scan_time}".strip(" at") if scan_date else "your scheduled date"

                if pa_status == "none":
                    items.append(
                        f"MRI_VISIT_DONE_AUTH_MISSING: {first_name} already visited {doc_name} and received "
                        f"the MRI prescription for {body_part} ({reason}). The doctor visit is COMPLETE — "
                        f"do NOT suggest {first_name} needs to see the prescribing doctor again. "
                        f"The scan is booked with {scan_provider} on {scan_when}. "
                        f"However prior authorization has NOT been submitted yet. "
                        f"On your first response: tell {first_name} their prescription is ready and scan is booked, "
                        f"then immediately call notify_provider targeting {doc_name}'s office with "
                        f"notification_type='prior_auth_request' to kick off the auth, "
                        f"then say: 'Everything is lined up — I've just notified Dr. [doc]'s office to submit "
                        f"the prior auth to Cigna. Once it clears (2-5 business days), you're all set for your scan.'"
                    )
                elif pa_status == "pending":
                    items.append(
                        f"MRI_VISIT_DONE_AUTH_PENDING: {first_name} already visited {doc_name} and received "
                        f"the MRI prescription for {body_part}. The doctor visit is COMPLETE — "
                        f"do NOT suggest {first_name} needs to see the prescribing doctor again. "
                        f"The scan is booked with {scan_provider} on {scan_when}. "
                        f"Prior auth was submitted on {pa_date} and is currently PENDING Cigna approval "
                        f"(Ref# {pa_ref}). "
                        f"On your first response: open with a warm update — "
                        f"'Hello {first_name}, your MRI prescription from {doc_name} is already in place and your scan "
                        f"is booked with {scan_provider} on {scan_when}. Cigna is reviewing the prior auth now "
                        f"(Ref# {pa_ref}, submitted {pa_date}); these usually clear in 2-5 business days.' "
                        f"Do NOT call notify_provider (already submitted). Do NOT offer to book again."
                    )
                elif pa_status == "approved":
                    items.append(
                        f"MRI_VISIT_DONE_AUTH_APPROVED: {first_name} already visited {doc_name} and received "
                        f"the MRI prescription for {body_part}. The doctor visit is COMPLETE — "
                        f"do NOT suggest {first_name} needs to see the prescribing doctor again. "
                        f"The scan is booked with {scan_provider} on {scan_when}. "
                        f"Prior auth is APPROVED by Cigna (Ref# {pa_ref}, valid through {pa_valid}). "
                        f"On your first response: open with good news in a calm, professional tone — "
                        f"'Hello {first_name}, good news: Cigna approved your prior authorization for the {body_part} MRI "
                        f"(Ref# {pa_ref}, valid through {pa_valid}), and your scan with {scan_provider} is booked for {scan_when}. "
                        f"You are all set — just show up as scheduled.' "
                        f"Do NOT call notify_provider. Do NOT offer to book again."
                    )
                elif pa_status == "declined":
                    items.append(
                        f"MRI_VISIT_DONE_AUTH_DECLINED: {first_name} already visited {doc_name} and received "
                        f"the MRI prescription for {body_part}. The doctor visit is COMPLETE. "
                        f"The scan was booked with {scan_provider} on {scan_when} but Cigna DECLINED the prior auth. "
                        f"On your first response: tell {first_name} clearly — 'You've got your prescription from "
                        f"Dr. [doc] and the scan is booked, but Cigna declined the prior auth. Here's what we can do: "
                        f"1) Appeal the decision — I can notify Dr. [doc]'s office to file an appeal, or "
                        f"2) We explore if there's an alternative imaging option Cigna will cover.' "
                        f"Ask which they'd prefer, then act immediately."
                    )

            else:
                # No imaging booking yet — standard flow, offer to find and book
                if pa_status == "none":
                    items.append(
                        f"MRI_PENDING_AUTH: {first_name} has an MRI prescription on file "
                        f"(ordered by {doc_name} for {body_part} — {reason}). "
                        f"The prior authorization has NOT been submitted yet. "
                        f"⚠️ CRITICAL OVERRIDE: The doctor visit for this issue is ALREADY DONE. "
                        f"Do NOT search for doctors, do NOT suggest seeing a specialist again, do NOT show provider cards for {body_part}. "
                        f"The ONLY next step is to get the prior auth submitted. "
                        f"On your FIRST response:\n"
                        f"  1. Start with a friendly greeting and confirm the visit: "
                        f"'Hello {first_name}, I see you visited {doc_name}" 
                        f"{(mri_rx.get('prescribed_date') and 'on ' + mri_rx.get('prescribed_date') or 'recently')} "
                        f"for {body_part} after your fall.'\n"
                        f"  2. Follow with the current status clearly and professionally: "
                        f"'Your MRI prescription is ready, but {doc_name}'s office has not yet sent the approval request to Cigna.'\n"
                        f"  3. Immediately call notify_provider targeting {doc_name}'s office with notification_type='prior_auth_request'.\n"
                        f"  4. After that, tell {first_name}: "
                        f"'I've just sent {_ensure_dr_prefix(doc_name)}'s office a reminder to submit the approval request to Cigna. "
                        f"These usually clear in 2-5 business days. The moment it comes through, I'll get your scan booked.'\n"
                        f"  5. Then ask: 'Would you like me to find an imaging center near you so we're ready?'\n"
                        f"WAIT for {first_name}'s reply before calling find_providers. Do NOT auto-book.\n"
                        f"TONE RULE: Be professional, warm, and concise. No insurance jargon. No explanations the member hasn't asked for. "
                        f"If {first_name} asks 'what is prior auth?' THEN explain it briefly — not before.\n"
                        f"If {first_name} then mentions {body_part} symptoms again, "
                        f"do NOT start a new provider search — instead say: "
                        f"'You already have an MRI prescription from {doc_name} for your {body_part} — "
                        f"we're just waiting on Cigna's approval before booking the scan.'"
                    )
                elif pa_status == "pending":
                    items.append(
                        f"MRI_AUTH_PENDING: {first_name} has an MRI prescription on file "
                        f"(ordered by {doc_name} for {body_part}). "
                        f"Prior auth was submitted on {pa_date} and is currently PENDING Cigna approval "
                        f"(Ref# {pa_ref}). "
                        f"⚠️ CRITICAL OVERRIDE: The doctor visit is ALREADY DONE. "
                        f"Do NOT search for new doctors. Do NOT suggest another appointment for {body_part}. "
                        f"On your first response, open with a warm update: "
                        f"'Hello {first_name}, I see you visited {doc_name} "
                        f"{(mri_rx.get('prescribed_date') and 'on ' + mri_rx.get('prescribed_date') or 'recently')} "
                        f"for {body_part}. Cigna is reviewing the approval request now (Ref# {pa_ref}); these usually clear in 2-5 business days.' "
                        f"Then ask: 'Would you like me to find an imaging center near you so you're ready the moment it comes through?' "
                        f"If {first_name} mentions {body_part} symptoms again, remind them the prescription is on file and auth is pending — "
                        f"do NOT launch another doctor search."
                    )
                elif pa_status == "approved":
                    items.append(
                        f"MRI_AUTH_APPROVED: {first_name} has an MRI prescription on file "
                        f"(ordered by {doc_name} for {body_part}). "
                        f"Prior auth is APPROVED by Cigna (Ref# {pa_ref}, valid through {pa_valid}). "
                        f"⚠️ CRITICAL OVERRIDE: The doctor visit is DONE. Do NOT search for new doctors or specialists. "
                        f"Do NOT call find_providers or check_availability automatically. "
                        f"On your FIRST response: begin with a warm update — "
                        f"'Hello {first_name}, I see you visited {doc_name} "
                        f"{(mri_rx.get('prescribed_date') and 'on ' + mri_rx.get('prescribed_date') or 'recently')} "
                        f"for {body_part}. Good news: Cigna has approved your prior authorization for the {body_part} MRI "
                        f"(Ref# {pa_ref}, valid through {pa_valid}).' "
                        f"Then ask: 'Would you like me to find imaging centers near you and get it booked, "
                        f"or is there something else I can help you with today?' "
                        f"WAIT for {first_name}'s reply. Only call find_providers(specialty='Radiology') AFTER they confirm they want to book the scan."
                    )
                elif pa_status == "declined":
                    items.append(
                        f"MRI_AUTH_DECLINED: {first_name} has an MRI prescription on file "
                        f"(ordered by {doc_name} for {body_part}). "
                        f"Prior auth was DECLINED by Cigna. "
                        f"⚠️ CRITICAL OVERRIDE: The doctor visit is DONE. Do NOT suggest a new doctor visit. "
                        f"On your first response: proactively inform {first_name} and explain next steps "
                        f"(appeal the decision or explore alternative imaging options Cigna will cover)."
                    )
    except Exception:
        pass

    # ── Referral status from provider dashboard ───────────────────────────────
    try:
        referral = ref_pre if member_state is not None else storage.get_referral(user_id)
        if referral and referral.get("status") == "approved":
            specialist    = referral.get("specialist", "the specialist")
            approved_by   = referral.get("approved_by", "your PCP")
            approved_date = referral.get("approved_date", "")
            valid_through = referral.get("valid_through", "")
            ref_reason    = referral.get("reason", "")
            # Check if a specialist booking already exists for this referral
            _existing_specialist_booking = None
            for _b in (bookings or []):
                _b_reason = (_b.get("reason") or "").lower()
                _b_prov   = (_b.get("provider_name") or "").lower()
                _spec_lc  = specialist.lower()
                if any(kw in _b_reason or kw in _b_prov for kw in _spec_lc.split()):
                    _existing_specialist_booking = _b
                    break

            if not _existing_specialist_booking:
                items.append(
                    f"REFERRAL_APPROVED: {first_name}'s PCP ({approved_by}) has referred them to see a {specialist} "
                    f"(approved {approved_date}, valid through {valid_through}"
                    + (f", reason: {ref_reason}" if ref_reason else "")
                    + f"). The referral is fully cleared.\n"
                    f"On your FIRST response: warmly tell {first_name} the referral came through from {approved_by} "
                    f"and ask: 'Would you like me to find a {specialist} near you now?' "
                    f"WAIT for their reply before calling any tools. Do NOT auto-search or call find_providers."
                )
    except Exception:
        pass

    # ── PCP change status ─────────────────────────────────────────────────────
    try:
        pcp_changes = storage.read(f"pcp_changes/{user_id}.json") or []
        for c in pcp_changes:
            if c.get("status") == "pending":
                items.append(
                    f"PCP_CHANGE_PENDING: {first_name} submitted a PCP change request to "
                    f"{c.get('new_pcp_name', 'a new doctor')} which is currently pending Cigna approval. "
                    f"Proactively mention this status if relevant to the conversation."
                )
            elif c.get("status") == "completed" and not c.get("_proactive_shown"):
                items.append(
                    f"PCP_CHANGE_COMPLETED: {first_name}'s PCP has been updated to "
                    f"{c.get('new_pcp_name', 'a new doctor')} — Cigna approved the change. "
                    f"Proactively congratulate {first_name} and confirm the new PCP details."
                )
    except Exception:
        pass

    # ── MRI Required flag set by provider on specialist bookings ─────────────
    # Only fires when mri_required=True on a completed booking AND no prescription
    # has been issued yet. If a prescription already exists, the MRI_PENDING_AUTH
    # block above already covers the full flow — skip this to avoid conflict.
    try:
        # We REMOVED the mri_already_prescribed check here entirely based on Option 1.
        # Now, the "Mark MRI Required" flag on the booking is the STRICT gatekeeper.
        # The agent ignores the mri_prescription file during the initial proactive 
        # greeting UNLESS the booking also has mri_required=True.
        bookings_all = bk_pre if member_state is not None else storage.get_bookings(user_id)
        
        # Check if any completed booking has mri_required set to True
        mri_flagged_booking = None
        for b in (bookings_all or []):
            if b.get("mri_required") and b.get("status") == "completed":
                mri_flagged_booking = b
                break
                
        if mri_flagged_booking:
            # Ok, the UI toggle is ON. Now check if the prescription is already on file.
            _mri_already_prescribed = _has_mri_prescription(
                mri_rx_pre if member_state is not None else storage.get_mri_prescription(user_id)
            )
            
            if not _mri_already_prescribed:
                _spec_name = mri_flagged_booking.get("provider_name", "your specialist")
                _b_reason  = mri_flagged_booking.get("reason", "")
                _b_date    = mri_flagged_booking.get("date", "")
                items.append(
                    f"MRI_REQUIRED_FLAG: The specialist ({_spec_name}) you saw on {_b_date} "
                    f"has indicated that an MRI scan is required"
                    + (f" related to: {_b_reason}" if _b_reason else "")
                    + f". The provider has flagged this in the system. "
                    f"On your FIRST response: let {first_name} know that {_spec_name} has recommended an MRI "
                    f"and that a prescription needs to be issued before the scan can be booked. "
                    f"Tell {first_name}: 'Dr. [name] has flagged that you need an MRI. "
                    f"The next step is getting a formal prescription — I can help coordinate that with Dr. [name]'s office. "
                    f"Once the prescription is issued, Cigna will need to approve it (prior authorization) before we book the scan.' "
                    f"Ask: 'Would you like me to reach out to Dr. [name]'s office to get the prescription started?' "
                    f"WAIT for their reply before calling any tools."
                )
    except Exception:
        pass

    # ── Plan change payer decision ────────────────────────────────────────────
    try:
        plan_change = _st.get("plan_change") if member_state is not None else storage.read(f"plan_change/{user_id}.json")
        if plan_change and plan_change.get("payer_decision") and not plan_change.get("_payer_proactive_shown"):
            decision = plan_change["payer_decision"]
            new_plan_name  = plan_change.get("new_plan", "")
            prev_plan_name = plan_change.get("previous_plan", "")
            # Determine new plan's key rules for context
            _new_rules = _get_plan_rules(new_plan_name) if new_plan_name else {}
            _requires_ref = _new_rules.get("requires_referral", False)
            _pcp_copay    = _new_rules.get("pcp_copay", "")
            _spec_copay   = _new_rules.get("specialist_copay", "")
            if decision == "approved":
                items.append(
                    f"PLAN_CHANGE_APPROVED: Cigna has approved {first_name}'s request to switch "
                    f"from '{prev_plan_name}' to '{new_plan_name}'. "
                    f"New plan key rules — referral required: {_requires_ref}, "
                    f"PCP copay: {_pcp_copay}, specialist copay: {_spec_copay}. "
                    f"On your FIRST response: deliver the good news warmly. "
                    f"Mention 1-2 key changes that affect {first_name} (e.g. referral requirement, copay change). "
                    f"If {first_name} has any existing bookings, silently call find_providers on each doctor "
                    f"to check if they are still in-network under '{new_plan_name}' and surface any issues."
                )
            elif decision == "declined":
                items.append(
                    f"PLAN_CHANGE_DECLINED: Cigna has declined {first_name}'s request to switch plans. "
                    f"They remain on '{prev_plan_name}'. "
                    f"On your FIRST response: let {first_name} know gently, explain they're still on their "
                    f"current plan, and offer to help them choose a different plan or explore what's available."
                )
            # Mark as shown so it doesn't fire again — keep file until payer_decision is set
            if not dry_run:
                plan_change["_payer_proactive_shown"] = True
                storage.write(f"plan_change/{user_id}.json", plan_change)
    except Exception:
        pass

    # ── Follow-up check (14–30 day window, no appointment reminders) ─────────
    # Only fires when a completed visit is 14–30 days old with no follow-up booked.
    # > 30 days is excluded — too stale to nag about.
    try:
        bookings_all = (bk_pre if member_state is not None else storage.get_bookings(user_id)) or []
        _today = datetime.utcnow().date()

        def _parse_visit_date(s: str):
            if not s:
                return None
            s = s.replace(",", "").strip()
            for fmt in ("%A %B %d %Y", "%B %d %Y", "%Y-%m-%d", "%A, %B %d, %Y"):
                try:
                    return datetime.strptime(s, fmt).date()
                except ValueError:
                    pass
            return None

        completed_visits = [b for b in bookings_all if b.get("status") == "completed"]
        for visit in reversed(completed_visits):
            vd = _parse_visit_date(visit.get("date", ""))
            if not vd:
                continue
            age = (_today - vd).days
            if age < 14 or age > 30:
                continue
            provider = (visit.get("provider_name") or visit.get("provider") or "").strip()
            if not provider:
                continue
            # Check for any subsequent booking with this provider after the visit date
            has_followup = any(
                (b.get("provider_name") or b.get("provider") or "").strip().lower() == provider.lower()
                and _parse_visit_date(b.get("date", ""))
                and _parse_visit_date(b.get("date", "")) > vd
                for b in bookings_all
                if b is not visit
            )
            if not has_followup:
                reason = visit.get("reason", "your visit")
                items.append(
                    f"FOLLOW_UP_DUE: {first_name} saw {provider} {age} days ago "
                    f"(reason: {reason}) and has no follow-up booked. "
                    f"Mention it once, naturally — something like: "
                    f"'By the way, it's been {age} days since your visit with {provider} — "
                    f"is everything still going okay, or would you like to schedule a follow-up?' "
                    f"Say this ONCE only. Do not repeat it."
                )
                break  # surface one follow-up at a time
    except Exception:
        pass

    # ── MRI prescription expiry (> 30 days on file, scan not yet booked) ──────
    try:
        _mri_rx = (mri_rx_pre if member_state is not None else storage.get_mri_prescription(user_id)) or {}
        if _mri_rx.get("prescription_mri"):
            _prescribed_str = _mri_rx.get("prescribed_date", "")
            if _prescribed_str:
                _prescribed_dt = datetime.strptime(_prescribed_str[:10], "%Y-%m-%d").date()
                _rx_age = (datetime.utcnow().date() - _prescribed_dt).days
                _MRI_KW = {"mri", "scan", "imaging", "radiology"}
                _has_scan = any(
                    any(kw in (b.get("reason", "") + b.get("provider_name", "")).lower() for kw in _MRI_KW)
                    for b in (bookings_all or bk_pre or [])
                )
                _pa = (pa_pre if member_state is not None else storage.get_prior_auth(user_id)) or {}
                if _rx_age > 30 and not _has_scan and _pa.get("status") not in ("approved",):
                    _doc = (_mri_rx.get("prescribed_by") or {}).get("name", "your doctor")
                    items.append(
                        f"MRI_PRESCRIPTION_AGING: {first_name} has an MRI prescription from {_doc} "
                        f"that is {_rx_age} days old and no scan has been booked yet. "
                        f"Mention it once: 'Your MRI prescription from {_doc} is {_rx_age} days old — "
                        f"we should get that scan scheduled before it expires. "
                        f"Want me to find an imaging center?'"
                    )
    except Exception:
        pass

    if not items:
        return ""

    lines = "\n".join(f"  {i+1}. {item}" for i, item in enumerate(items))
    return f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROACTIVE ACTIONS REQUIRED — READ BEFORE RESPONDING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You have already reviewed {first_name}'s file. The following items are pending
and MUST be addressed proactively — do NOT wait for {first_name} to bring them up.
Address ALL of them naturally in your FIRST response, regardless of what {first_name} says.
Behave like a healthcare assistant who has already read the file before the patient walked in.

{lines}

IMPORTANT:
- Weave these naturally into your greeting — do not list them robotically
- If {first_name} says something unrelated (e.g. "I have a headache"), STILL address
  the pending items first, then handle their new request
- After addressing these items once, do not repeat them unless {first_name} asks
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


# ── System prompt builder ─────────────────────────────────────────────────────
def _build_system_prompt(user_id: str, travel_city: str = "", travel_state: str = "", member_state: dict | None = None) -> str:
    try:
        user = _users.get_user(user_id)
    except Exception:
        return "You are a compassionate healthcare assistant. Help members find the right doctor."

    plan_rules = _get_plan_rules(user.insurance_plan)
    memory     = _get_cached_memory(user_id)
    mh         = user.medical_history

    # Use pre-loaded state if provided, otherwise read from storage
    _st = member_state or {}
    bookings                = _st.get("bookings")   if member_state is not None else None
    _mri_rx_for_booking     = _st.get("mri_rx")     if member_state is not None else None
    _prior_auth_for_booking = _st.get("prior_auth") if member_state is not None else None
    if bookings is None:
        bookings = storage.get_bookings(user_id)
    if _mri_rx_for_booking is None:
        _mri_rx_for_booking = storage.get_mri_prescription(user_id)
    if _prior_auth_for_booking is None:
        _prior_auth_for_booking = storage.get_prior_auth(user_id)
    _MRI_KW = {"mri", "scan", "imaging", "radiology", "x-ray", "ct", "pet"}
    booking_block = ""
    if bookings:
        from datetime import datetime as _dt
        _now = _dt.now()

        def _booking_datetime(b: dict):
            """Parse booking date + time_start into a datetime for past/upcoming classification."""
            try:
                _raw_date = (b.get("date") or "").replace(",", "").strip()
                _raw_time = (b.get("time_start") or "").strip()
                for _sfx in (" PST", " EST", " CST", " MST", " PDT", " EDT", " CDT"):
                    _raw_time = _raw_time.replace(_sfx, "")
                _raw_time = _raw_time.strip()
                _combined = f"{_raw_date} {_raw_time}"
                for _fmt in ("%B %d %Y %I:%M %p", "%B %d %Y %I:%M%p",
                             "%b %d %Y %I:%M %p", "%Y-%m-%d %I:%M %p"):
                    try:
                        return _dt.strptime(_combined, _fmt)
                    except ValueError:
                        pass
            except Exception:
                pass
            return None

        booking_block = "\nBOOKINGS MADE THROUGH THIS APP:"
        for b in bookings[-5:]:
            reason_str  = f" for {b['reason']}" if b.get('reason') else ""
            b_reason_lc = (b.get("reason") or "").lower()
            b_prov_lc   = (b.get("provider_name") or "").lower()
            is_imaging  = any(kw in b_reason_lc or kw in b_prov_lc for kw in _MRI_KW)

            # Classify as UPCOMING or PAST using full datetime (date + time), not date-only.
            # This prevents same-day appointments that haven't happened yet from being
            # misclassified as past when the agent builds follow-up context.
            _bdt = _booking_datetime(b)
            if _bdt is not None:
                _appt_status = "UPCOMING" if _bdt > _now else "PAST"
            else:
                # Fallback: date-only when time cannot be parsed
                try:
                    _raw_date = (b.get("date") or "").replace(",", "").strip()
                    _bdate = None
                    for _fmt in ("%B %d %Y", "%b %d %Y", "%Y-%m-%d"):
                        try:
                            _bdate = _dt.strptime(_raw_date, _fmt).date()
                            break
                        except ValueError:
                            pass
                    _appt_status = "UPCOMING" if (_bdate and _bdate >= _now.date()) else "PAST"
                except Exception:
                    _appt_status = "UNKNOWN"

            if is_imaging and _mri_rx_for_booking and _mri_rx_for_booking.get("prescription_mri"):
                pa_st = (_prior_auth_for_booking or {}).get("status", "none")
                rx_doc = (_mri_rx_for_booking.get("prescribed_by") or {}).get("name", "specialist")
                booking_block += (
                    f"\n  - [{_appt_status}] {b.get('provider_name')} on {b.get('date')} at "
                    f"{b.get('time_start')} ({b.get('consultation_type', '')}){reason_str}"
                    f"  \u2190 SCAN APPOINTMENT [prescription already given by {rx_doc}; prior_auth={pa_st}; "
                    f"prescribing doctor visit is COMPLETE — do NOT treat this booking as a doctor consult]"
                )
            else:
                booking_block += (
                    f"\n  - [{_appt_status}] {b.get('provider_name')} on {b.get('date')} at "
                    f"{b.get('time_start')} ({b.get('consultation_type', '')}){reason_str}"
                )
    else:
        booking_block = "\nBOOKINGS MADE THROUGH THIS APP: None yet."

    dep_lines = ""
    if user.dependents:
        dep_lines = "\nDEPENDENTS ON THIS PLAN:\n" + "\n".join(
            f"  - {d['name']} ({d['relationship']}, DOB: {d['date_of_birth']})"
            for d in user.dependents
        )

    pcp_block = ""
    if user.assigned_pcp:
        pcp = user.assigned_pcp
        pcp_block = (
            f"\nASSIGNED PCP:"
            f"\n  Name:     {pcp.get('name', '')}"
            f"\n  NPI:      {pcp.get('npi', '')}"
            f"\n  Specialty:{pcp.get('specialty', '')}"
            f"\n  Address:  {pcp.get('address', '')}"
            f"\n  Phone:    {pcp.get('phone', '')}"
        )

    memory_block = ""
    if memory["has_history"]:
        memory_block = f"\nMEMBER HISTORY (from past sessions):\n{memory['context_block']}"

    # Load history summary from storage (long-term profile + recent summaries)
    # Use pre-loaded state if available to avoid a duplicate storage read
    history_summary = _st.get("history_summary") if member_state is not None else storage.get_history_summary(user_id)
    history_summary_block = ""
    if history_summary:
        history_summary_block = f"\n{history_summary}"
    
    # ── MRI Prescription + Prior Auth block ─────────────────────────────────
    mri_block = ""
    try:
        mri_rx     = _mri_rx_for_booking
        prior_auth = _prior_auth_for_booking

        # Member preference (e.g. preferred imaging provider)
        # Note: member_state snapshots use the key 'preferences' (plural) while
        # older code used 'preference' (singular). Try both when member_state
        # is provided; otherwise read from storage.
        if member_state is not None:
            pref_blob = _st.get("preferences") or _st.get("preference") or storage.read(f"preferences/{user_id}.json")
        else:
            pref_blob = storage.read(f"preferences/{user_id}.json")
        preferred_provider = None
        if pref_blob and isinstance(pref_blob, dict):
            preferred_provider = pref_blob.get("preferred_imaging_provider") or pref_blob.get("preferred_provider")

        if _has_mri_prescription(mri_rx):
            doc_name  = mri_rx.get("prescribed_by", {}).get("name", "your specialist")
            doc_spec  = mri_rx.get("prescribed_by", {}).get("specialty", "")
            body_part = mri_rx.get("body_part", "")
            rx_reason = mri_rx.get("reason", "")
            rx_date   = mri_rx.get("prescribed_date", "")
            pa_status = (prior_auth or {}).get("status", "none")
            pa_ref    = (prior_auth or {}).get("auth_reference_number", "")
            pa_sub_by   = prior_auth.get("submitted_by", doc_name)
            pa_sub_date = prior_auth.get("submitted_date", "")
            pa_app_date = prior_auth.get("approved_date", "")
            pa_valid    = prior_auth.get("valid_through", "")
            pa_payer    = prior_auth.get("payer", "Cigna")

            mri_block = (
                f"\nMRI PRESCRIPTION ON FILE:"
                f"\n  Ordered by: {doc_name}{' (' + doc_spec + ')' if doc_spec else ''}"
                f"\n  Procedure:  MRI — {body_part}"
                f"\n  Reason:     {rx_reason}"
                f"\n  Date:       {rx_date}"
                f"\n  IMPORTANT: The ordering physician for this MRI is exclusively {doc_name}."
                f"\n  Always use this exact name for notify_provider calls."
                f"\n  Never substitute with any doctor from MEDICAL HISTORY or PAST APPOINTMENTS."
            )

            if prior_auth:
                if pa_status == "none":
                    mri_block += "\n  Prior Auth: Not yet submitted."
                elif pa_status == "pending":
                    mri_block += (
                        f"\n  Prior Auth: PENDING — awaiting {pa_payer} approval"
                        + (f"\n    Submitted by:  {pa_sub_by}'s office" if pa_sub_by else "")
                        + (f"\n    Submitted on:  {pa_sub_date}" if pa_sub_date else "")
                        + (f"\n    Ref#:          {pa_ref}" if pa_ref else "")
                    )
                elif pa_status == "approved":
                    mri_block += (
                        f"\n  Prior Auth: APPROVED by {pa_payer}"
                        + (f"\n    Ref#:          {pa_ref}" if pa_ref else "")
                        + (f"\n    Approved on:   {pa_app_date}" if pa_app_date else "")
                        + (f"\n    Valid through: {pa_valid}" if pa_valid else "")
                    )
            else:
                mri_block += "\n  Prior Auth: Not yet submitted."
        # Append remembered preference so the agent knows the user's preferred imaging provider
        try:
            if preferred_provider and (preferred_provider.get('provider_name') or preferred_provider.get('npi')):
                pp = preferred_provider
                pp_name = pp.get('provider_name') or ''
                pp_spec = pp.get('specialty') or ''
                pp_city = pp.get('city') or ''
                pp_addr = pp.get('address') or ''
                loc = pp_city or pp_addr
                mri_block += f"\n  Member Preference: prefers {pp_name}{(' (' + pp_spec + ')') if pp_spec else ''}{(' — ' + loc) if loc else ''}. Prefer this provider when booking the scan unless unavailable or out-of-network."
        except Exception:
            pass
    except Exception:
        mri_block = ""
    # ─────────────────────────────────────────────────────────────────────────

    # Plan change context — use pre-loaded state if available, else read from storage
    # get_and_clear_plan_change returns None when payer_decision exists (handled by proactive block)
    # but we still need the plan_change_block in the system prompt for the __plan_change_greeting__ session
    # so we read it directly from member_state when payer_decision is present
    _raw_plan_change = _st.get("plan_change") if member_state is not None else storage.read(f"plan_change/{user_id}.json")
    plan_change = None
    if _raw_plan_change:
        if _raw_plan_change.get("payer_decision") and not _raw_plan_change.get("_payer_proactive_shown"):
            # Payer decided but member hasn't seen the greeting yet — inject the block
            plan_change = _raw_plan_change
        elif not _raw_plan_change.get("payer_decision"):
            # No payer decision yet — use get_and_clear to mark _initial_shown
            if not _raw_plan_change.get("_initial_shown"):
                plan_change = storage.get_and_clear_plan_change(user_id)
    plan_change_block = ""
    if plan_change:
        previous_plan = plan_change["previous_plan"]
        plan_change_block = f"""

        PLAN CHANGE DETECTED — first session after plan change:
        Previous Plan: {previous_plan}
        New Plan:      {user.insurance_plan}

        ⚠️ IMMEDIATE ACTION REQUIRED ON THIS SESSION:

        1. UPCOMING BOOKINGS — CHECK FIRST BEFORE RESPONDING:
        Look at BOOKINGS MADE THROUGH THIS APP right now.
        If there are any bookings listed:
        → Your VERY FIRST response must acknowledge the plan change and flag the booking.
        → Naturally weave it into your greeting — do not wait for the member to ask.
        → Then silently call find_providers with that doctor's name to check network status
            under the new plan, and tell the member the result in the same response.
        → If out-of-network: offer to find an in-network alternative.
        → If still in-network: reassure them warmly.
        If there are no bookings: skip this step entirely.

        2. PAST DOCTORS — ACT WHEN MENTIONED:
        If {user.first_name} mentions any doctor from MEDICAL HISTORY,
        silently call find_providers with that doctor_name to check network status.
        - Out-of-network → tell them naturally, offer in-network alternative
        - Still in-network → confirm warmly: "Good news — Dr. X is still covered."

        3. PLAN RULES — ENFORCE IMMEDIATELY:
        New plan rules are already in PLAN BENEFITS above.
        Apply them from this moment — referral, prior auth, copays all follow {user.insurance_plan}.
        If previous plan had no referral and new plan requires one, surface it the first
        time a specialist is mentioned.
        NOTE: If the user's message is exactly "__plan_change_greeting__", treat it as a silent 
        system trigger. Do NOT echo or reference that text. Just deliver your proactive 
        plan-change greeting naturally as if you initiated it.
        Do NOT mention the plan change again after this session. Behave completely normally."""




    # ── Proactive block — built from storage, injected into prompt ──────────
    proactive_block = _build_proactive_block(user_id, user.first_name, dry_run=True, member_state=member_state)
    # ─────────────────────────────────────────────────────────────────────────

    med_block = ""
    if mh.get("conditions"):
        med_block += f"\nMEDICAL HISTORY:"
        med_block += f"\n  Conditions:    {', '.join(mh['conditions'])}"
    if mh.get("allergies"):
        med_block += f"\n  Allergies:     {', '.join(mh['allergies'])}"
    if mh.get("current_medications"):
        med_block += f"\n  Medications:   {', '.join(mh['current_medications'])}"
    if mh.get("past_appointments"):
        med_block += f"\n  Past Doctors:"
        seen = set()
        for a in mh["past_appointments"]:
            key = a.get("npi", a.get("doctor_name", ""))
            if key not in seen:
                seen.add(key)
                med_block += (
                    f"\n    - {a['doctor_name']} ({a['specialty']}) — "
                    f"{a['visit_count']} visit(s), last: {a['date']}, reason: {a['reason']}"
                )

    referral_note = (
        f"REQUIRES a PCP referral before seeing a specialist. "
        f"Member's assigned PCP is {user.assigned_pcp.get('name', 'their PCP')} "
        f"(NPI: {user.assigned_pcp.get('npi', '')})."
        if plan_rules["requires_referral"]
        else "No referral required — member can book specialists directly."
    )

    prior_auth_note = (
        "Prior authorization required for imaging, surgery, and specialist visits."
        if plan_rules["prior_auth_required"]
        else "No prior authorization required for standard specialist visits."
    )

    return f"""You are a sharp, proactive healthcare concierge for Medilife Healthcare.
You are speaking with {user.first_name} {user.last_name} (Member ID: {user.member_id}).
Think of yourself as a knowledgeable friend who understands medicine, insurance, and how to get things done fast.
{user.first_name} may not know what kind of doctor they need or how insurance works — that's exactly why they're here. You handle it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MEMBER CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Name:         {user.first_name} {user.last_name}
  Age:          {user.age}
  Phone:        {user.phone}
  Home City:    {user.default_city}, {user.default_state}
  Current City: {travel_city + ", " + travel_state if travel_city else user.default_city + ", " + user.default_state}{"  ← TRAVELLING" if travel_city else ""}
  ZIP:          {user.zip_code}
  Insurance:    {user.payer_name} — {user.insurance_plan}
  Member Since: {user.member_since}
  PCP Copay:    {plan_rules['pcp_copay']} | Specialist: {plan_rules['specialist_copay']} | Telehealth: {plan_rules['telehealth_copay']}
  Deductible:   {plan_rules['deductible']} | OOP Max: {plan_rules['oop_max']}
  Premium:      {plan_rules['monthly_premium']}
  Referral:     {referral_note}
  Prior Auth:   {prior_auth_note}
  Plan Notes:   {plan_rules['notes']}{dep_lines}{pcp_block}{med_block}{booking_block}{history_summary_block}{memory_block}{plan_change_block}{mri_block}{proactive_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR DECISION AUTHORITY — THE CORE RULE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE GOLDEN RULE:
  If you have enough to act → ACT immediately. Do not narrate your plan. Do not ask "Should I?".
  If you genuinely need one specific piece of info to proceed → ask exactly ONE targeted question. Then act.

  ⚠️ VAGUE SYMPTOM RULE — CRITICAL:
  If the member says something like "stomach ache", "stomach pain", "belly hurts", "I feel sick",
  "my back hurts", "I have a headache" — these are VAGUE. You do NOT have enough to act.
  You MUST ask clarifying questions first.  Do NOT call find_providers on a vague symptom.
  The ONLY exception: member has an established specialist for this exact condition in PAST DOCTORS and you have to mention that in response if you chooose this exception for your action.

  ⚠️ UNCERTAINTY / PCP FALLBACK RULE — METHODICAL TRIAGE:
  If the member says "I don't know" or "not sure" during triage:
  1. PERSISTENCE: Do NOT pivot to Primary Care or guess a specialist immediately. Treat "I don't know" as a neutral response.
  2. PROTOCOL EXHAUSTION: You MUST complete the entire 3-question sequence (Q1 → Q2 → Q3) defined in the SYMPTOM TRIAGE PROTOCOL before giving up on specialty mapping. 
     - If they don't know the answer to Q1, proceed to ask Q2. 
     - If they don't know the answer to Q2, proceed to ask Q3.
  3. FINAL FALLBACK: Only after the user's THIRD response—if you still cannot determine the specialty or urgency—should you invoke the PCP fallback.
  4. REASONING NARRATIVE: When falling back after 3 attempts, you MUST explain that because the symptoms are clinically ambiguous, seeing a PCP first is the SAFEST next step to ensure they get the right diagnosis and aren't misrouted.
  5. AUTHORITY: On your 4th message (after the 3rd 'I don't know'), YOU decide that Primary Care is the required path.

⚠️ ONE QUESTION PER MESSAGE — NON-NEGOTIABLE:
  When asking clarifying questions, ask EXACTLY ONE question per message.
  NEVER combine two questions in one message, even with "and" or "also".
  VIOLATION: "Where is the pain — upper or lower? And is it sharp or cramping?"
  CORRECT: "Where exactly is the discomfort — upper belly, lower belly, or all over?"
  Wait for the answer. Then decide if another question is needed before acting.

YOU DECIDE — NEVER ASK {user.first_name} ABOUT THESE:
  ✓ Which medical specialty they need (you reason from symptoms + history)
  ✓ Routine vs urgent vs emergency (you assess from what they describe)
  ✓ In-Person vs Telehealth (clinical judgment — see CARE TYPE below)
  ✓ Whether prior auth or referral applies (you know their plan)
  ✓ Which provider to recommend (top_pick from results)
  ✓ Whether to check availability after finding providers (always yes)
  ✓ Whether to check the next day if today is empty (always yes, silently)

ONLY {user.first_name} CAN DECIDE — THE ONLY MOMENTS YOU PAUSE:
  ✓ Which time slot they prefer (after you show real options from check_availability)
  ✓ Which insurance plan to switch to (after you explain the choices)
  ✓ Whether to proceed with an out-of-network doctor or find an in-network alternative

THE AUTONOMOUS TOOL CHAIN — DO THIS WITHOUT ASKING:
  1. Specialty identified → determine plan type first (PPO vs HMO) — this changes EVERYTHING
  2. PPO plan → book specialist directly: find_providers → check_availability → book_appointment
  3. HMO plan → MUST go through PCP first: find_providers(PCP) → check_availability → book PCP → STOP
     The PCP sees the member, then raises the referral. Specialist cannot be booked before that visit.
  4. HMO + referral IS approved → full specialist chain: find_providers(specialist) → check_availability → book_appointment
  5. Specialist orders MRI → specialist raises prior auth (NOT the agent, NOT the PCP)
     The agent's role: inform member, show imaging centers, wait for payer approval
  6. Prior auth approved → find imaging center: find_providers(Radiology) → check_availability → book_appointment

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 2 — SYMPTOM TRIAGE: USE WHAT YOU KNOW FIRST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚨 RULE ZERO — CHECK MRI PRESCRIPTION ON FILE BEFORE ANYTHING ELSE 🚨
  Before doing ANY symptom triage or provider search, look at MRI PRESCRIPTION ON FILE in MEMBER CONTEXT.
  If a prescription exists AND the body_part matches what the member is describing:
    → The clinical journey for that issue is ALREADY past the "see a doctor" stage.
    → Do NOT search for doctors. Do NOT suggest another specialist. Do NOT show provider cards.
    → Instead: tell the member about the prescription and get them to submit the prior auth.
    → Then take the EXACT action dictated by that status (see PRIOR AUTHORIZATION section below).

  EXAMPLES OF THIS RULE IN ACTION:
  ✅ Prescription on file: "Right Knee" — member says "my knee still hurts":
     → "I can see Dr. [specialist] already wrote you a prescription for an MRI of your right knee.
        We're just waiting on Cigna's sign-off before booking your scan — no need to see another doctor."
     → Then immediately handle the prior auth status (remind office / show imaging centers / book scan).
  ✅ Prescription on file: "Lower Back" — member says "my back pain hasn't improved":
     → Same — surface the prescription, don't start a new provider search.
  ❌ NEVER do this when a prescription is on file for that body part:
     find_providers("Orthopaedic Surgery") or find_providers("Primary Care") for that same symptom.

BEFORE asking anything, scan the MEMBER CONTEXT above:
  → Do their conditions, medications, or past doctors already answer this? → Use it, act on it.
  → Have they seen a relevant specialist before? → Call find_providers with that doctor_name.
  → Is the specialty obvious from what they said? → Act immediately, no questions.

WHEN YOU ACT WITHOUT ANY QUESTION:
  "I have a rash" → Dermatology
    PPO: find_providers(Dermatology) → check_availability → book
    HMO with no referral: find_providers(PCP) → check_availability → book PCP visit first
    HMO with referral approved for Dermatology: find_providers(Dermatology) → check_availability → book
  "I need a cardiologist" → Cardiology
    PPO: find_providers(Cardiology) immediately
    HMO: book PCP first (referral must come from PCP, not requested by agent)
  "chest tightness for 3 days" → Cardiology, urgent
    PPO: find_providers(Cardiology, urgency=urgent) immediately
    HMO: this is urgent — book PCP same-day/urgent; PCP will refer if needed
  "my back is hurting" + chronic back pain in history + has a spine/neuro doctor → find_providers with their doctor (any plan — established relationship)
  "headache" + migraines in history + has a neurologist → find_providers with that neurologist (any plan — continuity of care)
  "I need an MRI" → read MRI PRESCRIPTION ON FILE above → act per prior auth status (see PRIOR AUTH below)
  "my MRI prescription" / "mri prescription" / "check my prescription" → read MRI PRESCRIPTION ON FILE above first
    → If prescription exists: tell the member what it's for, who ordered it, and the prior auth status
      Then IMMEDIATELY execute the correct action based on prior auth status (see PRIOR AUTH section below)
      Do NOT ask "which doctor ordered it?" — the prescription is already on file
    → If no prescription on file: ask who ordered it
  "stomach pain, worse after eating" + GERD in history → Gastroenterology, find their GI doctor
  "I feel dizzy" + on Lisinopril (BP med) → "This could be related to your blood pressure medication, let me get you to a cardiologist"

SYMPTOM TRIAGE PROTOCOL — CLARIFYING QUESTIONS

  WHEN TO SKIP CLARIFICATION ENTIRELY (act immediately):
  - Member has an established specialist for this condition in PAST DOCTORS → book them directly
  - Symptom is unambiguous: "I need a cardiologist", "I have a rash", "my knee hurts after running"
  - Urgency is obvious: chest pain + sweating/arm pain, stroke symptoms, can't breathe → 911 immediately
  - Member already gave enough detail: "sharp pain upper right abdomen for 3 days with fever"

  ⚠️ ADAPTIVE TRIAGE PROTOCOL — CLINICAL REASONING:
  1. ANALYZE (CDA): Check user input for Onset (how long?), Geography (where exactly?), and Mechanism (injury/gradual/activity).
  2. ADAPTIVE BRANCHING — FOLLOW THIS LOGIC:
     - HIGH DETAIL: If user provides all 3 CDA pillars (e.g. "Knee pain from running for 4 days"), SKIP all questions and call find_providers immediately.
     - PARTIAL DETAIL: If 1-2 pillars are met, ask EXACTLY ONE targeted clarifying question for the missing info.
     - VAGUE/AMBIGUOUS: If 0 pillars are met (e.g. "skin issue", "leg pain"), you MUST ask AT LEAST TWO sequential clarifying questions (Q1 then Q2) in two separate turns before calling any tools. You are STRICTLY FORBIDDEN from calling find_providers or any other tool on the first or second turn of a vague symptom.
  3. REASONING MODIFIERS — CLINICAL BEST PRACTICE:
     - IF Duration > 2 days OR Mechanism = Injury/Activity → Route to Specialist (for PPO).
     - IF Duration <= 2 days AND Mechanism = Unknown/Gradual:
       → PPO: Route to Specialist. Show OON options immediately if in-network search fails. Do NOT fallback to PCP unless search (including OON) is a total dead end.
       → HMO: Route to PCP for conservative care safety check with proper clinical reasoning.
     - IF Severity = High (Red Flags: sudden worst pain, thunderclap headache, numbness, fever) → Route to ER/911.
  4. PERSISTENCE: Treat "I don't know" as neutral. Never stop triage or guess a specialist on the first "I don't know." Methodically move to the next pillar.
  5. THREE-STRIKE FALLBACK: Only after the 3rd attempt—if you cannot determine the specialty or urgency—should you pivot to a PCP evaluation for safety.
  6. PLAN-AWARE ACTION — NO ASKING FOR SEARCH PERMISSION:
     - If in-network search fails for a PPO user, you MUST immediately call find_providers again or use the OON results provided. Do NOT ask "Would you like me to widen?" or "Should I check telehealth?". Simply show the results and explain the OON costs.
     - PPO: Route to Specialist (including OON) if mapped.
     - HMO: Always route to PCP for new symptoms, but explain the specialty context.

  TONE FOR CLARIFYING QUESTIONS:
  - EMPATHY FIRST: Every response to a symptom MUST open with one brief, warm acknowledgement (The Empathy Rule).
  - CLUSTER QUESTIONS: Ask for related details together (e.g. "What happened and how long has it been bothering you?") to be efficient.
  - CLINICAL RELEVANCE: Questions MUST be specific to the symptom mentioned. Use your internal knowledge to ask the most diagnostic questions for that area.
  - Wait for the answer. Then decide if another question is needed before acting. Max 3 questions total.

CARE TYPE — YOU DECIDE, NEVER ASK:
  Always In-Person: MRI, CT, X-ray, lab work, surgery, physical therapy, fever, injury, chest pain, rash, eye issues, anything needing a physical exam
  Telehealth appropriate: mental health follow-up, medication refill/review, mild cold or cough, test result discussion, anxiety check-in
  When ambiguous, default to In-Person.

⚠️ ADVISORY FOLLOW-UP RULE — CRITICAL:
  When {user.first_name} asks a clarifying or advisory question AFTER providers have already been shown
  (e.g. "should I go in-person or telehealth?", "which one is better?", "is this urgent?",
  "do I need a referral?", "what's the difference?") — this is a CONVERSATIONAL response only.
  → Answer the question directly and concisely in 2-3 sentences.
  → End with a brief nudge like "Go ahead and tap a card above to book."
  → DO NOT re-list provider names, ratings, distances, or availability.
  → DO NOT re-render provider cards — the member can already see them.
  → DO NOT repeat the plan context sentence — it was already said.
  The provider cards only re-render when the underlying provider list has actually changed
  (new search, different specialty, different urgency). Not for advisory questions.

URGENCY — YOU DECIDE:
  Emergency: chest pain + sweating/arm pain, stroke symptoms (face drooping, slurred speech), severe bleeding, can't breathe → tell {user.first_name} to call 911 immediately
  Urgent: fever over 101°F, significant uncontrolled pain, infection signs, rapidly worsening symptoms → urgency="urgent"
  Routine: everything else → urgency="routine"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 3 — THE REAL-WORLD CARE PATHWAY (FOLLOW THIS EXACTLY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

UNDERSTAND THE FULL CLINICAL JOURNEY FIRST:
  Real healthcare works in a clear sequence — never skip steps, never go backwards.

  ┌─────────────────────────────────────────────────────────────────────┐
  │  PPO PLAN (no referral required):                                   │
  │  Member has symptoms                                                │
  │    → Book specialist directly (find_providers → book)              │
  │    → Specialist sees member, may order MRI/imaging                 │
  │    → SPECIALIST raises prior auth to payer (not the agent, not PCP)│
  │    → Payer approves → Member books imaging center                  │
  │    → Member goes for scan                                          │
  └─────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────┐
  │  HMO PLAN (referral required):                                      │
  │  Member has symptoms                                                │
  │    → Book PCP FIRST (find_providers(PCP) → book)                  │
  │    → PCP sees member, decides if specialist is needed              │
  │    → PCP raises referral to specialist (not the agent)             │
  │    → Payer approves referral                                        │
  │    → THEN book specialist (find_providers(specialist) → book)      │
  │    → Specialist sees member, may order MRI/imaging                 │
  │    → SPECIALIST raises prior auth to payer                         │
  │    → Payer approves → Member books imaging center                  │
  │    → Member goes for scan                                          │
  └─────────────────────────────────────────────────────────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PPO PLAN — DIRECT SPECIALIST ACCESS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{referral_note}

  PPO members need NO referral. Book directly with the specialist.
  Full chain: find_providers(specialist) → check_availability → book_appointment
  No notify_provider needed for referral (PPO has no referral requirement).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HMO PLAN — PCP FIRST, ALWAYS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{referral_note}

  HMO members MUST see their PCP before a specialist. The PCP is the gateway.
  The agent's job is to help the member book the RIGHT next step in the journey.

  STEP 1 — MEMBER HAS NEW SYMPTOMS, NO SPECIALIST HISTORY:
    → The correct action is to book a PCP appointment, NOT a specialist.
    → Narrative: Explain that since they are on an HMO plan, they must see their assigned PCP (Dr. [Name]) first for a referral. (Follow the ORDERING RULE below).
    → find_providers(specialty="Primary Care", doctor_name="[assigned PCP name]", routing_reason="[brief symptom summary from member]") → check_availability → book
    → CRITICAL: When calling find_providers for the assigned PCP, your internal thought MUST explicitly state why you are doing it based on the member's symptoms. 
      - If the symptoms are unclear or gradual, your thought MUST be something like: "Calling the find_providers tool to route to Primary Care because the member reported gradual lower leg pain. PCP evaluation is appropriate for new or unclear symptoms to ensure proper diagnosis."
      - If the symptoms are sudden/recent, your thought MUST be something like: "Calling the find_providers tool to route to Primary Care because the member reported sudden severe pain lasting 2 days. An urgent PCP evaluation is appropriate for new short-duration symptoms."
      - Do NOT say "Member mentioned a specific doctor" because the member did not mention them, you are proactively selecting them based on the plan rules.
    → DO NOT call notify_provider for a referral — the referral comes from the PCP AFTER the visit, not before.
    → DO NOT book a specialist directly. DO NOT show specialist cards.
    → EXCEPTION: If member has an established specialist (in PAST DOCTORS) — continuity of care applies,
      skip PCP gate and book that specialist directly, any plan.

  STEP 2 — REFERRAL IN PROACTIVE ACTIONS (PCP already issued referral):
    → The PCP has ALREADY seen the member and issued the referral. PCP visit is DONE.
    → This is the moment to book the specialist.
    → find_providers(specialist from referral) → check_availability → book_appointment
    → Narrative: Explain that their PCP referral has been approved, so they are now cleared to see a specialist. (Follow the ORDERING RULE below).

  STEP 3 — MEMBER SAYS "I HAVE A REFERRAL" OR ASKS ABOUT REFERRAL STATUS:
    → Check storage. If approved: run find_providers(specialist) → check_availability → book
    → If pending: tell them it's not approved yet, offer to follow up.
    → Never send a new notify_provider for referral — referrals come from PCPs, not from the app.

  NEVER DO THESE FOR HMO:
  ✗ Do NOT book a specialist before a PCP visit for new/unknown symptoms
  ✗ Do NOT call notify_provider(referral_request) as if the app can trigger a referral — only PCPs raise referrals after physically seeing the patient
  ✗ Do NOT skip the PCP step even if the member asks to go straight to a specialist

  SHOWING SPECIALIST CARDS WITH REFERRAL LOCK — ONLY WHEN MEMBER EXPLICITLY INSISTS:
  If the member has already been told about the referral requirement AND explicitly asks to see
  specialists anyway (e.g. "can you show me the cardiologists anyway?", "I just want to see who's
  available", "show me the heart specialists near me") — THEN and ONLY THEN:
  → Call find_providers(specialty="Radiology") → check_availability → proceed to booking.

  WHEN {user.first_name} EXPLICITLY ASKS TO BOOK AN MRI/IMAGING APPOINTMENT:
    Check prior_auth status FIRST before doing anything.

    If status = "none" or "pending":
      → Do NOT call check_availability. Do NOT call book_appointment.
      → Explain clearly: "I can't book the scan until Cigna approves the prior auth.
        [If none: Your specialist's office needs to submit it — I've sent them a reminder.]
        [If pending: It's already been submitted and is sitting with Cigna right now (Ref# [ref]).]
        The moment it's approved, I'll get you scheduled. Here are imaging centers near you so we're ready:"
      → HARD STOP. No booking.

    If status = "approved":
      → Proceed: find_providers(Radiology) → check_availability → book_appointment.
      → Tell {user.first_name}: "Cigna already approved this — let me get that booked for you now."

  If {user.first_name} says "I already have approval" and stored status shows none/pending:
    → Trust them completely. Proceed: find_providers → check_availability → book_appointment.

  When NO MRI PRESCRIPTION ON FILE exists but member mentions needing an MRI:
    → The specialist orders MRIs, not the member directly. Ask: "Did your doctor order this scan?"
    → If they say yes: ask which doctor so you can send a reminder to their office.
    → If specialist is on file (in PAST DOCTORS): use that doctor's name for notify_provider(follow_up_reminder).
    → Never ask twice. Never pretend the agent can submit prior auth itself.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FOLLOW-UP / REVISIT PATTERN — PROACTIVE PAST APPOINTMENT LOOKUP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When {user.first_name} says something like:
  "I want a follow-up to my previous [ear/heart/knee] appointment"
  "Can I reschedule with the doctor I saw before?"
  "I want to revisit my [specialist type]"
  "Book me another appointment with my [condition] doctor"

DO THIS (in order):
  1. Check past_appointments in MEDICAL HISTORY above.
  2. Find the most recent visit with a matching specialty or condition.
  3. Extract the specialty from that past appointment (e.g., Otolaryngology from an ear appointment).
  4. DO NOT ask "which doctor did you see?" — you already have that information from the history.
  5. Immediately call find_providers(specialty='[extracted_specialty]') to show current in-network options.
  6. Open with: "I can see you saw [Dr. Name] for [reason] on [date]. Let me find the best options for your follow-up."

This is NOT a generic new provider search — it's a continuation of an existing care thread.
The agent proactively uses past context to skip clarifying questions and go straight to booking.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 5 — AVAILABILITY & BOOKING: NO CONFIRMATION LOOPS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
After find_providers returns → immediately call check_availability on top_pick with no appointment_date. Do not ask.
The tool automatically finds the next day with open slots — no manual retrying needed.

Present availability results naturally, highlighting the soonest option — DO NOT list multiple individual time slots:
  "Dr. [X] has earliest availability **[today/tomorrow]**, [Day] [Date] at **[Earliest Time]** — tap the card to pick a time and book."
The UI renders a booking card with the slots — your job is to confirm availability exists and
tell {user.first_name} to use the card. Never enumerate times like "2:00 PM, 2:30 PM, 3:30 PM".
Do NOT repeat the system message about "No slots available today" if you are already describing the availability tomorrow. Keep your response conversational.

ALWAYS include one plain-language sentence about what their plan means for this booking.
This sentence must appear ONCE and ONLY ONCE in your response — do not repeat it:
  PPO plan → " a PPO, you can book this specialist directly — no referral needed."
  HMO plan → "Since you're on an HMO, you'll need a referral from Dr. [PCP] before seeing a specialist."
  HMO + referral approved → "Your referral from Dr. [PCP] is already cleared, so you're good to go."
  Keep it to one sentence. Plain language. No insurance jargon.

  ⚠️ PCP BOOKING EXCEPTION — SKIP THE PLAN SENTENCE ENTIRELY:
  When the booking IS the PCP visit (i.e. the provider being booked IS {user.first_name}'s assigned PCP,
  or the specialty is Primary Care / Family Medicine / Internal Medicine / General Practice),
  do NOT include the plan context sentence at all.
  Referral rules only apply when seeing a specialist — they are irrelevant and confusing when
  the member is booking their own PCP directly. Omit it silently.

  ⚠️ IMAGING/RADIOLOGY BOOKING EXCEPTION — SKIP THE PLAN SENTENCE ENTIRELY:
  When the booking is for an imaging center or radiology provider (MRI, CT, X-ray, scan),
  do NOT include the plan context sentence about PPO/referral.
  The reason they can book is the PRIOR AUTH APPROVAL — not the plan type.
  Instead say something like: "Your prior auth is approved, so you're all set to book."
  Omit the referral sentence silently.

When {user.first_name} selects a time via the booking card → immediately call book_appointment. No "just to confirm?" loop.
The only moment you pause before booking: their choice is genuinely ambiguous ("the morning one" when there are 3 morning slots).

OUT-OF-NETWORK DOCTOR:
  CORE POLICY — IN-NETWORK FIRST, ALWAYS:
  ✅ ALWAYS try to find an in-network provider first.
  ❌ Out-of-network is the ABSOLUTE LAST RESORT — only surface OON results when:
     a) find_providers exhausted the search radius and found ZERO in-network providers (oon_fallback=true), AND
     b) The member genuinely needs a physical visit (not something that can wait or be done via telehealth)

  Member asks for a specific doctor → doctor comes back out-of-network:
  → "Dr. [X] is out-of-network under your plan — that means higher out-of-pocket costs instead of your in-network {plan_rules['specialist_copay']} copay. Want to go ahead with Dr. [X], or should I find an in-network [specialty] nearby?"
  → They confirm Dr. [X] → check_availability and book normally.
  → They want in-network → call find_providers without doctor_name.
  Doctor is in-network → proceed silently. No network mention needed.

  find_providers returns oon_fallback=true (no in-network found):

  - ACT AUTONOMOUSLY: If no in-network providers are found near the member (even after widening the search), you MUST immediately proceed to find alternative care options without asking the member for permission.
  - PRIORITY: 1) Check for Telehealth options, 2) Show Out-of-Network (OON) providers.
  - REASONING: Explain that you have searched via widening and are unable to find in-network providers, so you've looked at telehealth and out-of-network options to ensure they get care quickly.
  - FINANCIAL TRANSPARENCY: When showing OON providers, YOU MUST proactively calculate and mention their financial impact. 
    → Tell the member: "Since these options are out-of-network, a typical consultation will cost around **$150** out-of-pocket. This will count toward your **{plan_rules['oop_max']}** annual out-of-pocket maximum."
    → Framed this as helpful, empathetic guidance so there are no surprise bills.

  CASE B — Urgent (fever, significant pain, infection, worsening symptoms):
  → Tell {user.first_name} upfront: "I wasn't able to find any in-network [specialty] doctors near [city].
     Since this sounds urgent, here are your closest available options — keep in mind these are
     out-of-network, so you will be responsible for the full cost of the visit until you reach your **{plan_rules['oop_max']}** annual out-of-pocket maximum.
     If you can, an urgent care or ER visit will always see you regardless of network."
  → Show OON providers immediately — do not delay treatment for cost reasons.
  → Always mention that the ER is an option for emergencies regardless of network.

  CASE C — Emergency (chest pain + radiation, stroke symptoms, can't breathe, severe bleeding):
  → Tell {user.first_name} to call 911 immediately. Network status is irrelevant in life-threatening situations.
  → Do not search for providers.

  find_providers returns oon_fallback=false (in-network found):
  → Never mention out-of-network providers. Show only the in-network results returned.
  → Do NOT add OON providers alongside in-network results as "alternatives".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PLAN CHANGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When {user.first_name} wants to change plans:
  1. Ask why — one question. Helps you recommend the right plan.
  2. Based on their reason, filter the plans down to only the ones that actually address
     what they asked for. Present those options briefly, then IMMEDIATELY give your
     recommendation and why. 
     
     CRITICAL FORMATTING RULE: When comparing options, DO NOT clump everything into a single dense paragraph. 
     You MUST use bullet points. Because of how the frontend parses text, each plan's details MUST be on a SINGLE line next to the bullet point, separated by pipe characters (|). DO NOT use line breaks inside a single bullet point.
     Compare no more than 2 or 3 plans to avoid overwhelming the member.
     
     EXAMPLE (member wants cost benefits):
     "Your current plan costs $19/month. Here are the best low-cost alternatives:
     
     • **Cigna Total Care Plus (HMO D-SNP):** $0/mo premium | $0 deductible | $2,000/yr OOP max | Requires PCP referral
     • **Cigna Total Care (HMO D-SNP):** $0/mo premium | $0 deductible | $2,500/yr OOP max | Requires PCP referral
       
     **My Recommendation:** I suggest the **Total Care Plus** plan because it gives you the $0 premium you want while capping your yearly out-of-pocket costs at just $2,000. Want me to switch you over?"
  3. Confirm ONCE only — ask "Just to confirm — you'd like to switch to [plan name]?" ONLY when the member
     said something vague like "the PPO one" or "the cheaper one".
     ⚠️ AMBIGUOUS YES RULE — CRITICAL: If your previous message offered MORE THAN ONE plan as options
     and the member replies with just "yes", "ok", "sure", or any positive word WITHOUT naming a specific plan,
     do NOT call request_plan_change. Instead ask: "Which plan would you like — [list the options briefly]?"
     You must have a single unambiguous plan name before calling request_plan_change. Never guess. 
     If the member already named the exact plan (e.g. "Cigna True Choice Access Medicare (PPO)"), that IS
     their confirmation — call request_plan_change immediately. Do NOT ask again.
     If the member said "yes" in reply to your confirmation question, call request_plan_change immediately.
     NEVER ask a second confirmation question. One confirm max, and only when the plan name is ambiguous.
  4. Call request_plan_change immediately after confirmation.
  5. After request_plan_change succeeds, tell {user.first_name}:
     "I've submitted your request to switch to [new plan name] to Cigna for approval. A representative will review it —
      once approved, your new plan takes effect immediately and I'll let you know the moment you log back in."
     Always mention the exact new plan name in this confirmation message.
  6. Mention: network may change, any affected bookings will be flagged next session.
  7. Always state the monthly premium of the current plan and the new plan when comparing.
     Example: "Your current plan costs $19/month. Cigna True Choice Medicare (PPO) is $78/month but has no referral requirement and a larger network."
  8. If the member asks which plan is cheapest, recommend the $0/month HMO options and explain the trade-off (referral required).
  9. Never say you don't have cost or premium data — it is always available in PLAN BENEFITS above.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LOCATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{user.first_name}'s location: {travel_city + ", " + travel_state if travel_city else user.default_city + ", " + user.default_state}{"  (travelling — home is " + user.default_city + ", " + user.default_state + ")" if travel_city else ""}
For ALL find_providers calls pass travel_city='{travel_city}' and travel_state='{travel_state}'.
NEVER ask {user.first_name} where they are — location is already known.
{"Out-of-network providers at the travel location cost more — mention this briefly and naturally if it comes up." if travel_city else ""}
If radius expanded beyond 10 miles, mention it naturally: "I had to look a bit further out — about [X] miles."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CARE TYPE CONVERSION OR REVERSAL — EXISTING BOOKING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When {user.first_name} asks to convert an existing in-person appointment to telehealth, OR changes their mind and asks to revert/switch back to in-person (e.g., "revert it to in-person", "change my mind", "keep it as in-person itself"):

  STEP 1: Look at BOOKINGS MADE THROUGH THIS APP above. Find the upcoming booking.
  STEP 2: Call book_appointment IMMEDIATELY with:
    - npi           = NPI from that booking
    - provider_name = provider_name from that booking
    - time_slot     = time_start from that booking (e.g. "12:00 PM CST") — USE THIS EXACTLY
    - appointment_date = date from that booking — USE THIS EXACTLY
    - consultation_type = requested mode ("Telehealth" or "In-Person")
    - reason        = same reason as the original booking
  STEP 3: DO NOT call check_availability. DO NOT offer alternative slots. The slot is confirmed, you are just updating the mode (Telehealth <-> In-Person).
  STEP 4: Confirm: "Done! Switched your [date] appointment with [Dr. X] back to [In-Person/Telehealth] at [time]."

  If the NPI is missing from the booking: call find_providers(doctor_name="[name]") to get it,
  then immediately call book_appointment with the existing date and time_start. Still no availability check.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HARD CONSTRAINTS — NEVER VIOLATE THESE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✗ Never call book_appointment without a time_slot from actual check_availability results
✗ EXCEPTION TO THE ABOVE: When converting or reverting an existing booking (Telehealth <-> In-Person), use the exact time_slot and appointment_date from BOOKINGS MADE THROUGH THIS APP — do NOT call check_availability first. The slot is already confirmed. Just update consultation_type.
✗ Never call book_appointment when prior_auth status is "none" or "pending" for imaging
✗ Never book a specialist for an HMO member who has not yet seen their PCP (no referral on file)
✗ Never call notify_provider(referral_request) — referrals are raised by PCPs after a visit, not by this app
✗ Never pretend the agent can submit prior auth — only the specialist's office can do that
✗ Never say "Should I search?", "Want me to check availability?", "How does that sound?", "Shall I go ahead?"
✗ Never ask {user.first_name} which specialty, doctor type, or care setting — those are your decisions
✗ Never call notify_provider for prior auth as if it were a submission — only use it as a reminder to the specialist's office
✗ Never say "I don't have that information" if it's anywhere in MEMBER CONTEXT above
✗ Never use a 1–10 pain scale — ask naturally like a person, not a form
✗ Never show specialist cards to HMO members as a "preview" before PCP referral — UNLESS the member
  explicitly insists on seeing them after being told about the referral requirement. In that case,
  call find_providers and show cards with the referral lock button. Never call check_availability or
  book_appointment for these locked cards.
✗ NEVER search for providers for a body part that already has an MRI prescription on file — the clinical
  journey is past that stage. Surface the prescription + prior auth status instead. This applies even
  if the member complains about pain in that area again — they need the scan, not another doctor visit.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOOLS — CALL IMMEDIATELY WHEN CONDITIONS ARE MET
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
find_providers(user_id="{user_id}", specialty, urgency, doctor_name="", travel_city="{travel_city}", travel_state="{travel_state}")
  → Call the moment specialty is known. Always pass user_id and travel params.
  → Response: top_pick, providers list, radius_miles (mention if >10 miles), searched_city.
  → CRITICAL: If response contains imaging_prior_auth_gate field with ⛔, READ IT and obey it.
    It will tell you whether to call notify_provider, block booking, or proceed normally.
    Never ignore imaging_prior_auth_gate. It is a hard system instruction, not a suggestion.

notify_provider(user_id="{user_id}", provider_name, notification_type, message)
  → notification_type: "prior_auth_request" | "referral_request" | "follow_up_reminder"
  → Call immediately when needed. Tell {user.first_name} what you did and what happens next.

check_availability(user_id="{user_id}", npi, provider_name, appointment_date="")
  → Call immediately after find_providers on top_pick. Leave appointment_date empty to get the next available day automatically.
  → The tool auto-advances day by day (up to 7 days) until it finds open slots — you never need to retry manually.

book_appointment(user_id="{user_id}", npi, provider_name, time_slot, consultation_type, appointment_date, reason)
  → Call the moment {user.first_name} picks a slot. time_slot must exactly match check_availability output.
  → consultation_type: "In-Person" or "Telehealth" — your clinical decision or user request.
  → Always pass reason (e.g. "knee pain follow-up", "MRI scan head", "annual wellness visit").
  → If response contains previous_booking_cancelled=true: you MUST inform the user that their conflicting home-location appointment with cancelled_provider_name on that same date has been automatically cancelled to avoid double-booking.
  → If response contains status="blocked": read the message field and tell {user.first_name} why it was blocked.
    For referral_required: show the providers, say you'll book the moment PCP approves.
    For prior_auth_required: show imaging centers, say you'll book the moment Cigna approves.
  → PRO TIP RULE: When an appointment is successfully booked (status="confirmed"), you MUST append a custom care guide to the very end of your response text. 
    Format it exactly like this:
    PRO_TIP_GUIDE: [Tip 1] | [Tip 2] | [Tip 3]
    Example: PRO_TIP_GUIDE: Rest and elevate your leg to reduce swelling | Avoid strenuous activities | Monitor for changes and go to urgent care if pain becomes severe
    These tips MUST be highly specific to the exact symptoms discussed by the member during triage.

request_plan_change(user_id="{user_id}", new_plan, new_plan_id, reason="")
  → Call immediately after {user.first_name} confirms the new plan.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TONE, STYLE & REASONING NARRATIVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Warm and direct. Always use {user.first_name}'s first name. You know them — show it naturally.

FORMATTING RULES — ALWAYS APPLY:
  - Bold doctor names: **Dr. John Smith**
  - Bold key plan facts: **PPO — no referral needed**, **HMO — referral required**
  - Bold appointment details: **today**, **tomorrow**, **May 30, 2026**, **2:00 PM PST**
  - Bold status outcomes: **approved**, **pending**, **confirmed**
  - Keep prose unbolded — only bold the facts the member needs to act on
  - No bullet lists for conversational responses — use natural sentences
  - Use bullet points only when listing 3+ provider options or multiple action steps

EMPATHY RULE — ONE SENTENCE, ALWAYS FIRST:
  Every response to a symptom or health concern MUST open with one brief acknowledgement
  that shows you heard what {user.first_name} said — before any clinical reasoning or action.
  Keep it to one sentence. Warm but not performative. Move on immediately after.
  ✓ GOOD: "That burning feeling in your upper belly sounds uncomfortable — let's get that sorted."
  ✓ GOOD: "A fall injury is definitely worth getting properly checked out."
  ✗ BAD: "I'm so sorry to hear you're experiencing that! That must be really difficult."
  ✗ BAD: Skipping empathy entirely and jumping straight to clinical reasoning.

MULTI-PROVIDER NARRATIVE RULE:
  When presenting provider results, never just name the top pick and go silent.
  Briefly explain WHY the top pick was chosen AND acknowledge the alternatives.
  Use a natural, friendly sentence structure (e.g. "I've picked **Dr. [Name]** as your best option and they are just **[X] miles** from you.").
  The reason must be specific — rating, distance, availability, or continuity of care.
  Never say "great options" without saying what makes them great.

EVERY response that involves finding providers OR answering a status question MUST start with
a short, warm, conversational paragraph BEFORE any provider cards or data. This is non-negotiable.

RULES FOR THE NARRATIVE:
  - Write like a knowledgeable friend who actually knows {user.first_name}, NOT a system log
  - NEVER open with "I've just notified..." or "I have searched..." — those are robotic
  - NEVER use clinical or insurance jargon: no "orthopedic specialist", "musculoskeletal",
    "prior authorization", "referral request", "HMO protocol", "in-network provider"
  - Use plain everyday language:
      "knee doctor" not "orthopedic surgeon"
      "I let your doctor's office know" not "I submitted a referral request"
      "your insurance just needs a quick sign-off" not "prior authorization is required"
      "I've lined up some great options near you" not "I searched for in-network providers"
  - Show that you already know {user.first_name}'s situation — reference their specific condition,
    their doctor's name, their history. Never sound like you're meeting them for the first time.
  - Sound warm and confident. {user.first_name} should feel looked after, not confused.
  - Keep the narrative to 2–4 sentences. Then show the cards/data.

BREVITY RULE — CRITICAL:
  Only say what the member needs right now. Do NOT volunteer background information they didn't ask for.
  ✗ BAD: "Before Cigna can cover the scan, they require a prior authorization — basically Cigna's
     approval that the MRI is medically necessary. This is standard for all imaging, regardless of your plan."
  ✓ GOOD: "I see Dr. [X]'s office hasn't sent the approval request to Cigna yet — I've just nudged them."
  If the member asks "why do I need approval?" or "what is prior auth?" — THEN explain it briefly.
  Otherwise, skip the explanation entirely. People come here to get things done, not to read a tutorial.

MIRROR RULE — NEVER INVENT DETAILS THE MEMBER DID NOT SAY:
  Only reference facts the member explicitly stated in their message. Never add details they did not provide.
  ✗ BAD: Member says "my knee hurts" → agent says "a week of knee pain" — member never said a week.
  ✗ BAD: Member says "I have a rash" → agent says "that rash you've had for a few days" — invented.
  ✓ GOOD: Member says "my knee hurts" → agent says "that knee pain" — mirrors exactly what was said.
  ✓ GOOD: Member says "my knee has been hurting for a week" → ONLY THEN say "a week of knee pain".
  This applies to duration, severity, body part specifics, and any other detail. Never assume. Never embellish.

ORDERING RULE — ALWAYS in this order, written naturally with no labels or headers:
  First: one empathy sentence acknowledging the symptom — warm, not performative.
  Second: one clinical reasoning sentence — what you inferred from their symptoms and why this specialty.
     This is MANDATORY every time you act (call a tool or map a specialty), even after a clarification exchange.
  Third: one plan context sentence (PPO/HMO rule — once, never repeated).
  Fourth: provider narrative — top pick with provider-specific reason (e.g. "top rated"), alternatives briefly mentioned. Do NOT repeat the clinical reasoning from Step 2 here.
  Fifth: availability confirmation — one line max: "Tap the card to pick a time and book."

  ⚠️ MULTI-TOOL NARRATIVE DEDUPLICATION:
  When calling multiple tools in a single turn (e.g., find_providers followed by check_availability), you MUST write the empathy, reasoning, and plan sentences ONLY ONCE at the very beginning of the overall response. Do NOT repeat the reasoning or "Since I couldn't find..." rationale for each tool call result. Combine the tool results into a single flowing narrative.

  NEVER narrate tool calls in the response. Do NOT say:
  ✗ "Let me check Dr. Jones's availability for you."
  ✗ "I'm searching for providers near you."
  ✗ "Dr. Jones has availability today" as a standalone sentence — fold it into the provider narrative.
  The card shows availability. Your job is context and reasoning, not narrating what the UI already shows.

NEVER jump straight to provider cards without the narrative. The narrative is required.
NEVER show provider cards before explaining the status context (e.g. prior auth pending/approved).
After the narrative text, the provider cards will be displayed automatically by the UI.

When you act (notify, search, book), tell {user.first_name} what you did and what comes next.
"What was my last booking?" → answer from BOOKINGS MADE THROUGH THIS APP in MEMBER CONTEXT above.
"What conditions do I have?" / "What medications am I on?" → answer directly from MEDICAL HISTORY above.
Emergency symptoms → tell {user.first_name} to call 911 immediately. Don't search for providers."""


def _nppes_search_cached(specialty: str, city: str, state: str, limit: int = 20) -> list:
    """Return NPPES results from cache when available, else call the API and cache the result."""
    cache_key = (specialty.lower(), city.lower(), state.lower(), limit)
    entry = _NPPES_CACHE.get(cache_key)
    if entry:
        results, ts = entry
        if _time.time() - ts < _NPPES_CACHE_TTL:
            return results
    results = _nppes_tool.search(specialty=specialty, zipcode="", city=city, state=state, limit=limit)
    _NPPES_CACHE[cache_key] = (results, _time.time())
    return results


# ── Tool 1: find_providers ────────────────────────────────────────────────────
def find_providers(
    user_id: str,
    specialty: str,
    urgency: str = "routine",
    doctor_name: str = "",
    travel_city: str = "",
    travel_state: str = "",
    routing_reason: str = "",
) -> dict:
    """
    Find and rank providers for a given specialty.
    Searches within 10 miles first, auto-expands to 25 then 50 if needed.
    Returns ranked list with top_pick marked and radius_miles used.
    Pass travel_city + travel_state when member is traveling outside their home city.
    Always pass user_id.
    """

    try:
        user = _users.get_user(user_id)
    except Exception as e:
        return {"error": str(e)}

    if not specialty:
        return {"error": "specialty is required"}

    # ── Imaging / Radiology prior-auth gate ───────────────────────────────────
    # If the member has an MRI prescription on file and prior auth is NOT approved,
    # we still return providers (so the agent can show options) but we inject a
    # hard gate flag that tells the agent to block booking and send notify_provider.
    _IMAGING_KWS = {"radiology", "diagnostic radiology", "imaging", "mri", "ct scan", "pet scan", "nuclear medicine"}
    _is_imaging_search = any(kw in specialty.lower() for kw in _IMAGING_KWS)
    _imaging_gate_status = None
    _imaging_gate_doc    = ""
    if _is_imaging_search:
        try:
            _mri_gate_rx = storage.get_mri_prescription(user_id)
            _mri_gate_pa = storage.get_prior_auth(user_id)
            if _mri_gate_rx and _mri_gate_rx.get("prescription_mri"):
                _imaging_gate_status = (_mri_gate_pa or {}).get("status", "none")
                _prescribed_by = _mri_gate_rx.get("prescribed_by", {})
                _imaging_gate_doc = (
                    _prescribed_by.get("name") if isinstance(_prescribed_by, dict) else str(_prescribed_by)
                ) or "the prescribing doctor"
        except Exception:
            pass

    if urgency == "emergency":
        return {
            "emergency": True,
            "message": "This is a medical emergency. Please call 911 or go to the nearest ER immediately.",
            "providers": [],
        }

    # Use travel location if member is away from home
    city  = travel_city.strip() if travel_city.strip() else user.default_city
    state = travel_state.strip() if travel_state.strip() else user.default_state
    is_traveling = bool(travel_city.strip() and travel_city.strip().lower() != user.default_city.lower())
    plan_id   = user.insurance_plan_id
    plan_name = user.insurance_plan
    history   = user.medical_history

    nucc_codes = _nucc.get_related_codes(specialty)

    if doctor_name:
        # First: check FHIR directory by exact NPI from bookings/history
        clean_name = doctor_name.replace("Dr.", "").replace("dr.", "").strip().upper()
        fhir_match = None
        for npi, role in _fhir_tool._npi_to_role.items():
            prac_ref = role.get("practitioner", {}).get("reference", "")
            prac_id  = prac_ref.split("/")[-1]
            prac     = _fhir_tool.repo.practitioners.get(prac_id, {})
            name_parts_prac = prac.get("name", [{}])[0]
            given  = " ".join(name_parts_prac.get("given", []))
            family = name_parts_prac.get("family", "")
            full   = f"{given} {family}".strip().upper()
            if clean_name in full or full in clean_name:
                net = _fhir_tool.validate_network(npi, plan_id)
                fhir_match = {
                    "npi": npi, "name": f"Dr. {given} {family}".strip(),
                    "network_status": net, "in_network": net == "in_network",
                    "source": "FHIR",
                }
                break
        if fhir_match:
            return {"found": True, "providers": [fhir_match], "count": 1, "searched_city": city, "routing_reason": routing_reason}
        # Fallback: NPPES name search
        last_name = doctor_name.replace("Dr.", "").replace("dr.", "").strip().split()[-1]
        name_parts = doctor_name.replace("Dr.", "").replace("dr.", "").strip().split()
        first_name_hint = name_parts[0].lower() if len(name_parts) > 1 else ""
        results = _nppes_tool.search_by_name(last_name=last_name, state=state, limit=10)
        if not results:
            results = _nppes_tool.search_by_name(last_name=last_name, limit=10)
        if first_name_hint:
            exact = [p for p in results if first_name_hint in p.to_dict().get("name", "").lower()]
            if exact:
                results = exact
        matches = []
        for p in results:
            p_dict = p.to_dict()
            net    = _fhir_tool.validate_network(p_dict.get("npi", ""), plan_id)
            p_dict["network_status"] = net
            p_dict["in_network"]     = net == "in_network"
            matches.append(p_dict)

        # Enforce strict slicing rules on name search results
        if specialty.lower() in ("primary care", "family medicine", "internal medicine"):
            matches = matches[:1]
        else:
            matches = matches[:3]

        return {"found": bool(matches), "providers": matches, "count": len(matches), "searched_city": city, "routing_reason": routing_reason}

    fhir_providers = _fhir_tool.search_providers(
        nucc_codes=nucc_codes, city="", state="", insurance_plan_id=plan_id
    )
    fhir_dicts = [p.to_dict() for p in fhir_providers]
    for p in fhir_dicts:
       # p["network_status"] = "in_network"
        p["source"]         = "FHIR"
        #p["in_network"]     = True

    seen_npis = {p.get("npi") for p in fhir_dicts if p.get("npi")}

    nppes_providers = _nppes_search_cached(specialty=specialty, city=city, state=state, limit=20)

    # If NPPES returned nothing, retry with alternate ae/e spelling or broader search
    if not nppes_providers:
        from app.tools.nppes_provider_tool import _normalize_specialty_for_nppes
        alt_specialty = _normalize_specialty_for_nppes(specialty)
        if alt_specialty.lower() != specialty.lower():
            nppes_providers = _nppes_search_cached(specialty=alt_specialty, city=city, state=state, limit=20)
        
        # BROADER FALLBACK: Search by state only if city search failed to find anyone
        if not nppes_providers:
            nppes_providers = _nppes_search_cached(specialty=alt_specialty or specialty, city="", state=state, limit=20)

    nppes_dicts = []
    for p in nppes_providers:
        d = p.to_dict()
        if d.get("npi") in seen_npis:
            continue
        net = _fhir_tool.validate_network(d.get("npi", ""), plan_id)
        d["network_status"] = net
        d["source"]         = "FHIR" if net == "in_network" else "NPPES"
        d["in_network"]     = net == "in_network"
        nppes_dicts.append(d)
        seen_npis.add(d.get("npi"))

    # Do NOT promote OON providers to in-network when no in-network NPPES found.
    # Keep them as OON — the oon_fallback flag in the return value will inform
    # the agent to warn the member. Honest representation matters here.

    all_providers = fhir_dicts + nppes_dicts

    if not all_providers:
        return {"providers": [], "count": 0, "message": f"No {specialty} providers found."}

    ranked = _ranking_tool.rank(
        providers         = all_providers,
        user_location     = (city, state),
        urgency           = urgency,
        insurance_plan    = plan_name,
        medical_history   = history,
        current_specialty = specialty,
    )

    audit_logger.log_event("PROVIDER_SEARCH", user_id, {
        "specialty": specialty, "urgency": urgency,
        "count": len(ranked),
        "in_network": sum(1 for p in ranked if p.get("in_network")),
    })

    # Build slim provider objects
    slim = []
    for p in ranked:  # Rank EVERYTHING first, don't truncate yet
        npi_key = p.get("npi", "")
        # ── Extract telehealth + phone from FHIR role ─────────────────────────
        _role = _fhir_tool._npi_to_role.get(npi_key, {})
        _telehealth = False
        _phone = ""
        for _ext in _role.get("extension", []):
            if _ext.get("url") == "telehealth_available":
                _telehealth = _ext.get("valueBoolean", False)
        # Phone priority: FHIR location telecom → NPPES (already on provider dict)
        for _loc_ref in _role.get("location", []):
            _loc_id = _loc_ref.get("reference", "").split("/")[-1]
            _loc = _fhir_tool.repo.locations.get(_loc_id, {})
            for _telecom in _loc.get("telecom", []):
                if _telecom.get("system") == "phone":
                    _phone = _telecom.get("value", "")
                    break
            if _phone:
                break
        if not _phone:
            _phone = (p.get("phone") or "").strip()

        # NPPES fallback: FHIR providers have no phone - look up by NPI.
        # If NPI search returns nothing, also try a name-based NPPES lookup.
        if not _phone and npi_key:
            try:
                _nppes_hit = _nppes_tool.search_by_npi(npi_key)
                if not _nppes_hit and p.get("name"):
                    _name = p.get("name", "").replace("Dr.", "").replace("dr.", "").strip()
                    parts = _name.split()
                    if len(parts) >= 2:
                        first_name = parts[0]
                        last_name = parts[-1]
                        results = _nppes_tool.search_by_name(
                            last_name=last_name,
                            first_name=first_name,
                            state=user.default_state,
                            limit=3,
                        )
                        if results:
                            _nppes_hit = results[0]
                if _nppes_hit:
                    _phone = (_nppes_hit.to_dict().get("phone") or "").strip()
            except Exception:
                pass

        _consultation = "Both" if _telehealth else "In-Person"
        slim.append({
            "name":             p.get("name", ""),
            "npi":              npi_key,
            "specialty":        p.get("specialty", ""),
            "organization":     p.get("organization", ""),
            "address":          p.get("address", ""),
            "in_network":       p.get("in_network", False),
            "network_status":   p.get("network_status", ""),
            "source":           p.get("source", ""),
            "rating":           p.get("rating"),
            "distance_miles":   p.get("distance_miles"),
            "distance":         p.get("distance", ""),
            "slots_today":      p.get("slots_today"),
            "top_pick":         p.get("top_pick", False),
            "top_pick_reason":  p.get("top_pick_reason", ""),
            "continuity_reason":p.get("continuity_reason", ""),
            "consultation":     _consultation,
            "phone":            _phone,
        })

    # Distance filtering with auto-expand: 10 → 25 → 50 miles
    # Providers with distance_miles=None are kept only as a last resort (unknown distance)
    def _within(providers, max_miles):
        return [p for p in providers if p.get("distance_miles") is not None and p.get("distance_miles") <= max_miles]

    # ── Separate pools by network status BEFORE distance filtering ──────────
    in_net_pool = [p for p in slim if p.get("in_network")]
    oon_pool    = [p for p in slim if not p.get("in_network")]

    # ── In-network filtering: 10 → 25 → 50 miles ──────────────────────────────
    filtered = _within(in_net_pool, 10); radius_used = 10
    if len(filtered) < 3:
        filtered = _within(in_net_pool, 25); radius_used = 25
    if len(filtered) < 3:
        filtered = _within(in_net_pool, 50); radius_used = 50

    # Strict Provider Card Display Rules
    if specialty.lower() in ("primary care", "family medicine", "internal medicine"):
        filtered = filtered[:1]  # PCP routing: show only the assigned PCP card
    else:
        filtered = filtered[:3]  # General search: show exactly 3 provider cards (max)

    # ── Out-of-network fallback — only when NO in-network providers found ────
    oon_fallback = False
    if not filtered:
        oon_fallback = True
        filtered = sorted(oon_pool, key=lambda x: (x.get("distance_miles") is None, x.get("distance_miles") or 999))
        
        # Apply strict length limits to OON fallback too
        if specialty.lower() in ("primary care", "family medicine", "internal medicine"):
            filtered = filtered[:1]
        else:
            filtered = filtered[:3]
            
        radius_used = None

    # Re-mark top_pick on filtered list
    if filtered and not filtered[0].get("top_pick"):
        filtered[0]["top_pick"] = True

    _imaging_gate_note = ""
    if _imaging_gate_status in ("none", "pending"):
        _imaging_gate_note = (
            f"⛔ PRIOR_AUTH_GATE: prior_auth.status='{_imaging_gate_status}'. "
            f"DO NOT call check_availability. DO NOT call book_appointment. "
            f"{'Call notify_provider(prior_auth_request) targeting ' + _imaging_gate_doc + ' immediately. ' if _imaging_gate_status == 'none' else 'Prior auth already submitted — do NOT re-notify. '}"
            f"Tell the member their insurance needs a quick sign-off before the scan can be scheduled. "
            f"Show these imaging centers so they are ready the moment approval comes through."
        )
    elif _imaging_gate_status == "approved":
        _imaging_gate_note = "✅ PRIOR_AUTH_APPROVED: Prior auth is approved. Proceed normally: check_availability → book_appointment."

    # ── Referral gate for HMO plans ─────────────────────────────────────────
    # If HMO plan requires referral and no approved referral exists, inject a
    # referral_gate flag so the frontend shows a lock button instead of "Click to Book".
    _referral_gate = False
    try:
        _plan_rules_fp = _get_plan_rules(plan_name)
        if _plan_rules_fp.get("requires_referral"):
            _ref_fp = storage.get_referral(user_id)
            _ref_approved_fp = _ref_fp and _ref_fp.get("status") == "approved"
            if not _ref_approved_fp:
                _referral_gate = True
    except Exception:
        pass

    return {
        "providers":        filtered,
        "count":            len(filtered),
        "specialty":        specialty,
        "urgency":          urgency,
        "top_pick":         filtered[0] if filtered else None,
        "radius_miles":     radius_used,
        "searched_city":    city,
        "is_travel_search": is_traveling,
        "imaging_prior_auth_gate": _imaging_gate_note,
        "referral_gate":    _referral_gate,
        "oon_fallback":     oon_fallback,
        "routing_reason":   routing_reason,
        "oon_fallback_note": (
            "⚠️ No in-network providers found. These are out-of-network options — "
            f"member will pay full out-of-pocket costs (~{_PLAN_RULES.get(plan_name.lower().strip(), {}).get('oop_max','see plan')} OOP max). "
            "Mention this clearly before showing results."
        ) if oon_fallback else "",
    }

# ── Tool 5: request_plan_change ───────────────────────────────────────────────
def request_plan_change(
    user_id: str,
    new_plan: str,
    new_plan_id: str,
    reason: str = "",
) -> dict:
    """
    Submit a plan change request on behalf of the member.
    Call after member confirms the new plan.
    Parameters:
      user_id     — always pass the member's user_id
      new_plan    — full name of the new insurance plan
      new_plan_id — plan ID of the new plan
      reason      — why the member wants to change (optional)
    """
    try:
        user             = _users.get_user(user_id)
        previous_plan    = user.insurance_plan
        previous_plan_id = user.insurance_plan_id
    except Exception as e:
        return {"error": str(e)}

    storage.save_plan_change(user_id, previous_plan, previous_plan_id, new_plan=new_plan, new_plan_id=new_plan_id)
    # Do NOT update the plan or plan_override yet — the plan only takes effect after payer approval.
    # _users.repo.update_plan and storage.update_plan are called in dashboard_router.plan_change_decision
    # when the payer approves. Updating here causes the payer portal to show the new plan before approval.

    audit_logger.log_event("PLAN_CHANGE_REQUESTED", user_id, {
        "previous_plan": previous_plan,
        "new_plan":      new_plan,
        "reason":        reason,
    })

    for k in [k for k in _runners if k.startswith(f"{user_id}|")]:
        _runners.pop(k, None)

    return {
        "status":         "submitted",
        "previous_plan":  previous_plan,
        "new_plan":       new_plan,
        "effective_note": "Plan change request submitted to Cigna (the payer) for approval. Once approved, the new plan takes effect immediately.",
        "next_step":      "A Cigna representative will review and approve the request. On your next login after approval, you will be notified of the confirmed plan change.",
        "network_note":   "Doctors in-network under your previous plan may not be in-network under your new plan.",
    }


# ── Tool 2: notify_provider ────────────────────────────────────────────
def notify_provider(
    user_id: str,
    provider_name: str,
    notification_type: str,
    message: str,
) -> dict:
    """
    Send a notification to a provider's office on behalf of the member.
    Use this when prior auth needs to be initiated, referral follow-up needed,
    or any care coordination task needs to be flagged to the provider.
    notification_type examples: "prior_auth_request", "referral_request", "follow_up_reminder"
    message: what to communicate to the provider's office
    """
    try:
        user = _users.get_user(user_id)
        member_name = f"{user.first_name} {user.last_name}"
    except Exception:
        member_name = user_id

    notification = {
        "member_id":         user_id,
        "member_name":       member_name,
        "provider_name":     provider_name,
        "notification_type": notification_type,
        "message":           message,
    }
    storage.save_notification(notification)
    audit_logger.log_event("PROVIDER_NOTIFIED", user_id, {
        "provider":          provider_name,
        "notification_type": notification_type,
    })
    return {
        "sent":     True,
        "provider": provider_name,
        "type":     notification_type,
        "summary":  f"Notification sent to {provider_name}'s office: {message[:100]}",
    }


# ── Tool: cancel_appointment ─────────────────────────────────────────────────
def cancel_appointment(
    user_id: str,
    provider_name: str,
    appointment_date: str,
) -> dict:
    """
    Cancel a specific appointment for a member.
    Marks the appointment as 'cancelled' in both appointments and bookings stores.
    Parameters:
      user_id          — always pass the member's user_id
      provider_name    — exact provider name from the booking
      appointment_date — exact date from the booking (e.g. "June 10, 2026")
    """
    provider_lc = provider_name.strip().lower()
    date_str    = appointment_date.strip()

    for store_key in (f"appointments/{user_id}.json", f"bookings/{user_id}.json"):
        records = storage.read(store_key) or []
        changed = False
        for r in records:
            r_provider = (r.get("provider_name") or r.get("provider") or "").strip().lower()
            r_date     = (r.get("date") or "").strip()
            if r_provider == provider_lc and r_date == date_str:
                r["status"] = "cancelled"
                changed = True
                break
        if changed:
            storage.write(store_key, records)

    # Invalidate runner so system prompt rebuilds without the cancelled booking
    for k in [k for k in _runners if k.startswith(f"{user_id}|")]:
        _runners.pop(k, None)

    audit_logger.log_event("BOOKING_CANCELLED", user_id, {
        "provider": provider_name,
        "date":     appointment_date,
    })
    return {"cancelled": True, "provider": provider_name, "date": appointment_date}


# ── Tool 3: check_availability ────────────────────────────────────────────────
def check_availability(
    user_id: str,
    npi: str,
    provider_name: str,
    appointment_date: str = "",
) -> dict:
    """
    Check available appointment slots for a specific provider.
    Parameters: user_id, npi, provider_name, appointment_date (optional, defaults to today).
    """
    try:
        city = _users.get_user(user_id).default_city
    except Exception:
        city = "Unknown"

    return check_provider_availability(
        npi=npi,
        provider_name=provider_name,
        city=city,
        consultation_mode="Both",
        appointment_date=appointment_date,
    )


# ── Tool 4: book_appointment ──────────────────────────────────────────────────
def book_appointment(
    user_id: str,
    npi: str,
    provider_name: str,
    time_slot: str,
    consultation_type: str,
    appointment_date: str = "",
    reason: str = "",
) -> dict:
    """
    Book an appointment. Only call after member confirms the time slot.
    consultation_type must be "In-Person" or "Telehealth".
    time_slot must exactly match a slot shown in check_availability results.
    appointment_date must match exactly what was shown in check_availability.
    reason: brief description of what the appointment is for (e.g. "MRI scan", "fever", "GERD follow-up")
    """
    try:
        user        = _users.get_user(user_id)
        city        = user.default_city
        member_city = user.default_city
    except Exception:
        city        = "Unknown"
        member_city = ""

    # ── Hard gate 1: Prior auth for imaging ───────────────────────────────────
    _IMAGING_KWS_BOOK = {"radiology", "imaging", "mri", "ct", "scan", "pet", "nuclear"}
    _reason_lc        = (reason or "").lower()
    _prov_lc          = (provider_name or "").lower()
    _is_imaging_book  = any(kw in _reason_lc or kw in _prov_lc for kw in _IMAGING_KWS_BOOK)
    if _is_imaging_book:
        try:
            _pa_check = storage.get_prior_auth(user_id)
            _pa_status_book = (_pa_check or {}).get("status", "none")
            if _pa_status_book in ("none", "pending"):
                _rx_check = storage.get_mri_prescription(user_id)
                _doc_check = ""
                if _rx_check and isinstance(_rx_check.get("prescribed_by"), dict):
                    _doc_check = _rx_check["prescribed_by"].get("name", "")
                return {
                    "status":  "blocked",
                    "reason":  "prior_auth_required",
                    "message": (
                        f"⛔ BOOKING BLOCKED — prior authorization status is '{_pa_status_book}'. "
                        f"Cigna must approve the prior auth before this imaging appointment can be booked. "
                        + (f"Notify {_doc_check}'s office to submit the prior auth request. " if _pa_status_book == "none" and _doc_check else "")
                        + "Do NOT attempt to book. Show imaging providers and tell the member you'll book the moment auth is approved."
                    ),
                }
        except Exception:
            pass

    # ── Hard gate 2: Specialist referral for HMO plans ────────────────────────
    try:
        _user_gate = _users.get_user(user_id)
        _plan_rules_gate = _get_plan_rules(_user_gate.insurance_plan)
        _pcp_specialties = {"family medicine", "internal medicine", "general practice", "primary care", "pediatrics"}
        # Determine if this booking is for a specialist (not PCP/imaging)
        _spec_lc = (
            next(
                (
                    s.get("display", "").lower()
                    for role in [_fhir_tool._npi_to_role.get(npi)]
                    if role
                    for sp in role.get("specialty", [])
                    for s in sp.get("coding", [])
                ),
                ""
            )
        )
        _is_pcp_booking   = any(ps in _spec_lc for ps in _pcp_specialties) or any(ps in _reason_lc for ps in _pcp_specialties)
        _is_imaging_booking = _is_imaging_book
        if _plan_rules_gate.get("requires_referral") and not _is_pcp_booking and not _is_imaging_booking:
            # Check if referral is approved for this specialist
            _ref_gate = storage.get_referral(user_id)
            _ref_approved = _ref_gate and _ref_gate.get("status") == "approved"
            if not _ref_approved:
                return {
                    "status":  "blocked",
                    "reason":  "referral_required",
                    "message": (
                        f"⛔ BOOKING BLOCKED — {_user_gate.insurance_plan} requires a PCP referral before booking a specialist. "
                        f"Referral status: {'not yet approved' if not _ref_gate else _ref_gate.get('status','none')}. "
                        f"Do NOT book until referral is approved. Show the member the providers and tell them you'll book the moment their PCP approves the referral."
                    ),
                }
    except Exception:
        pass

    if consultation_type not in ("In-Person", "Telehealth"):
        consultation_type = "In-Person"

    result = book_provider_appointment(
        npi=npi,
        provider_name=provider_name,
        city=city,
        time_slot=time_slot,
        consultation_type=consultation_type,
        consultation_mode="Both",
        member_city=member_city,
        appointment_date=appointment_date,
        member_id=user_id,
        reason=reason,
    )

    if result.get("status") == "confirmed":
        audit_logger.log_event("BOOKING_CONFIRMED", user_id, {
            "provider": provider_name,
            "date":     appointment_date,
            "time":     time_slot,
            "type":     consultation_type,
            "reason":   reason,
        })
        # Store reason in the booking record
        result["reason"] = reason

        # ── Care Transfer Auto-Cancellation ──────────────────────────────────
        try:
            def _get_specialty_display(provider_npi):
                try:
                    role = _fhir_tool._npi_to_role.get(provider_npi)
                    if role:
                        for sp in role.get("specialty", []):
                            for coding in sp.get("coding", []):
                                return coding.get("display", "").lower()
                except Exception: pass
                return ""

            new_spec = _get_specialty_display(npi)
            _user_bks = storage.get_bookings(user_id) or []
            _cancelled_any = False
            _cancelled_prov = ""

            for bk in _user_bks:
                bk_npi = bk.get("npi", "")
                bk_date = bk.get("date", "")
                bk_status = bk.get("status", "")

                if (
                    bk_npi != npi
                    and bk_status != "cancelled"
                    and bk_date == appointment_date
                    and _get_specialty_display(bk_npi) == new_spec
                ):
                    bk["status"] = "cancelled"
                    _cancelled_any = True
                    _cancelled_prov = bk.get("provider_name", "your home provider")
                    audit_logger.log_event("BOOKING_CANCELLED_BY_TRANSFER", user_id, {
                        "provider": _cancelled_prov,
                        "date": bk_date,
                    })
                    break

            if _cancelled_any:
                storage.write(f"bookings/{user_id}.json", _user_bks)
                _user_appts = storage.read(f"appointments/{user_id}.json") or []
                for ap in _user_appts:
                    if (
                        ap.get("npi") != npi
                        and ap.get("date") == appointment_date
                        and ap.get("status") != "cancelled"
                    ):
                        ap["status"] = "cancelled"
                storage.write(f"appointments/{user_id}.json", _user_appts)
                result["previous_booking_cancelled"] = True
                result["cancelled_provider_name"] = _cancelled_prov
        except Exception as ex:
            logger.error(f"Error in Care Transfer Auto-Cancellation: {ex}")

        # ── MRI prescription update: sync booked imaging provider ────────────
        try:
            from datetime import datetime as _dt
            _IMAGING_SPECIALTIES = {
                "Radiology",
                "Diagnostic Radiology",
                "Vascular & Interventional Radiology",
                "Imaging",
            }
            mri_rx = storage.get_mri_prescription(user_id)
            if _has_mri_prescription(mri_rx):
                booked_specialty = ""
                try:
                    role = _fhir_tool._npi_to_role.get(npi)
                    if role:
                        for s in role.get("specialty", []):
                            for coding in s.get("coding", []):
                                booked_specialty = coding.get("display", "")
                                break
                except Exception:
                    pass
                if booked_specialty in _IMAGING_SPECIALTIES:
                    storage.update_mri_prescription(user_id, {
                        "prescription_mri": True,
                        "prescribed_by": {
                            "name":      provider_name,
                            "specialty": booked_specialty,
                        },
                        "procedure":        mri_rx.get("procedure") or "MRI Scan",
                        "reason":           mri_rx.get("reason") or "Specialist recommended MRI",
                        "date":             _dt.now().strftime("%Y-%m-%d"),
                    })
                    pa = storage.get_prior_auth(user_id)
                    if pa:
                        pa["ordering_physician"] = provider_name
                        storage.save_prior_auth(user_id, pa)
        except Exception:
            pass
        # Invalidate all runners for this user (any travel variant)
        for k in [k for k in _runners if k.startswith(f"{user_id}|")]:
            _runners.pop(k, None)


    return result


# ── Reasoning trace helpers ───────────────────────────────────────────────────
# These build human-readable explanations of WHY the agent called each tool
# and WHAT it learned from the result — shown in the UI's Reasoning tab.

def _build_tool_thought(tool_name: str, args: dict, state: dict) -> str:
    """
    Returns a 1-2 sentence explanation of WHY the agent is calling this tool right now.
    Reads the args to be specific (specialty, provider name, etc.).
    """
    specialty    = args.get("specialty", "")
    doctor_name  = args.get("doctor_name", "")
    provider     = args.get("provider_name", "")
    notif_type   = args.get("notification_type", "")
    npi          = args.get("npi", "")
    new_plan     = args.get("new_plan", "")
    had_providers = bool(state.get("providers"))

    if tool_name == "find_providers":
        if doctor_name:
            # Check if this is the Primary Care routing (assigned PCP)
            is_pcp = False
            assigned_pcp_name = ""
            if state.get("memory") and state["memory"].get("assigned_pcp"):
                assigned_pcp_name = state["memory"]["assigned_pcp"].get("name", "")
            
            if specialty.lower() in ("primary care", "family medicine", "internal medicine") or (assigned_pcp_name and assigned_pcp_name.lower() in doctor_name.lower()):
                is_pcp = True

            if is_pcp:
                routing_reason = args.get("routing_reason", "").strip()
                symptoms_str = routing_reason if routing_reason else "symptoms needing evaluation"
                return f"Calling the find_providers tool to route to Primary Care because the member reported {symptoms_str}."
            return (
                f"Member mentioned a specific doctor ({doctor_name}). "
                f"Checking whether they are in-network and available."
            )
        if specialty:
            if specialty.lower() in ("primary care", "family medicine", "internal medicine"):
                routing_reason = args.get("routing_reason", "").strip()
                symptoms_str = routing_reason if routing_reason else "symptoms needing evaluation"
                return f"Calling the find_providers tool to route to Primary Care because the member reported {symptoms_str}."

            # Check if there is a matching history condition or past appointment
            has_history = False
            matching_cond = ""
            if state.get("memory"):
                conds = state["memory"].get("conditions", [])
                for c in conds:
                    if any(t in c.lower() for t in specialty.lower().split()):
                        has_history = True
                        matching_cond = c
                        break
                if not has_history:
                    past_appts = state["memory"].get("past_appointments", [])
                    if any(any(t in appt.get("specialty", "").lower() for t in specialty.lower().split()) for appt in past_appts):
                        has_history = True

            if has_history:
                history_clause = f"because it matches their medical history of {matching_cond}" if matching_cond else "because it matches their medical history"
                return (
                    f"Identified '{specialty}' as the right specialty {history_clause}. "
                    f"Routing directly to a specialist instead of a PCP, and searching for in-network options nearby."
                )
            else:
                return (
                    f"Identified '{specialty}' as the right specialty based on the symptom mechanism and duration. "
                    f"Routing directly to a specialist instead of a PCP, and searching for in-network options nearby."
                )
        return "Searching for matching providers."

    if tool_name == "check_availability":
        if provider:
            return (
                f"Selected {provider} as the top recommended provider. "
                f"Pulling their next available slots so the member can choose a time without delay."
            )
        if npi:
            return "Checking the top provider's availability automatically — no need for the member to ask."
        return "Checking appointment availability for the selected provider."

    if tool_name == "book_appointment":
        slot = args.get("time_slot", "")
        date = args.get("appointment_date", "")
        return (
            f"Member confirmed the {slot} slot on {date}. "
            f"Booking {provider} immediately — no confirmation loop needed."
        )

    if tool_name == "notify_provider":
        if notif_type == "prior_auth_request":
            return (
                f"MRI/imaging prescription is on file but prior authorization has not been submitted yet. "
                f"Notifying {provider}'s office to kick off the Cigna approval process now, "
                f"so the member doesn't have to follow up themselves."
            )
        if notif_type == "referral_request":
            return (
                f"Member's plan requires a PCP referral before seeing a specialist. "
                f"Sending a referral request to {provider} on the member's behalf "
                f"so the process starts immediately."
            )
        if notif_type == "follow_up_reminder":
            return (
                f"Appointment booked. Notifying {provider}'s office as a follow-up reminder "
                f"to ensure the prescribing doctor is in the loop."
            )
        return f"Sending a '{notif_type}' notification to {provider}'s office."

    if tool_name == "request_plan_change":
        return (
            f"Member confirmed they want to switch to '{new_plan}'. "
            f"Submitting the plan change request now."
        )

    return f"Calling {tool_name}."


def _build_tool_decision(tool_name: str, result: dict) -> str:
    """
    Returns a 1-3 sentence explanation of WHAT the agent learned from the tool result
    and what decision it makes next based on that result.
    """
    if tool_name == "find_providers":
        if result.get("emergency"):
            return "⚠️ Emergency detected — directing member to call 911."
        specialty  = result.get("specialty", "")
        if specialty.lower() in ("primary care", "family medicine", "internal medicine"):
            routing_reason = result.get("routing_reason", "").strip()
            symptoms_str = routing_reason if routing_reason else "symptoms needing evaluation"
            return f"Mapped the member's symptom to 'Primary Care' because the member reported {symptoms_str}. PCP evaluation is appropriate for new short-duration or unclear symptoms."

        count      = result.get("count", 0)
        top        = result.get("top_pick") or (result.get("providers") or [{}])[0]
        top_name   = top.get("name", "")
        top_reason = top.get("top_pick_reason", "")
        oon        = result.get("oon_fallback", False)
        gate       = result.get("imaging_prior_auth_gate", "")
        city       = result.get("searched_city", "")
        specialty  = result.get("specialty", "")
        reasoning  = result.get("_reasoning_context", "")

        parts = []
        
        # Parse the reasoning context dynamically provided by the agent via the _reasoning_context field.
        # If it doesn't exist, we fallback to a safe generic string.
        if reasoning and "[REASONING_CONTEXT:" in reasoning:
            # Extract just the first sentence (the reason) from the [REASONING_CONTEXT: ...] block
            cleaned_reason = reasoning.replace("[REASONING_CONTEXT: ", "").split(".")[0]
            # Replace the generic "You mapped" with a 3rd-person observer tone
            if cleaned_reason.startswith("You mapped"):
                cleaned_reason = cleaned_reason.replace("You mapped", "Mapped")
            parts.append(f"{cleaned_reason}.")
        elif specialty:
            # Fallback if no specific reasoning context was logged
            parts.append(f"Determined '{specialty}' is the appropriate care path based on the reported symptoms.")
            
        if count == 0:
            return "No providers found in the search area. Will try expanding the radius or alerting the member."
        if oon:
            parts.append(f"Could not find in-network providers near {city}, so retrieved {count} out-of-network option(s) instead.")
        else:
            parts.append(f"Successfully located {count} in-network {specialty} provider(s) near {city}.")
            
        if top_name:
            reason_note = f" (rated {top.get('rating')}/5.0 · {top.get('distance')} away)" if top.get('rating') else ""
            parts.append(f"Ranked {top_name} as the best match{reason_note}.")
            
        if "⛔" in gate:
            pa_status = "pending" if "pending" in gate else "not submitted"
            parts.append(
                f"Booking is blocked because prior auth is {pa_status}. "
                f"Showing providers as options only; scheduling will resume after Cigna approval."
            )
        elif "✅" in gate:
            parts.append("Prior auth is approved. Will now check availability to secure an appointment.")
        elif top_name and "⛔" not in gate:
            parts.append(f"Checking {top_name}'s schedule for the earliest available slots.")
            
        return " ".join(parts)

    if tool_name == "check_availability":
        provider   = result.get("provider_name", result.get("name", ""))
        date       = result.get("date", "")
        slots      = result.get("slots", [])
        skipped    = result.get("skipped_note", "")
        avail_text = result.get("available_times", [])

        slot_list  = slots or avail_text
        if not slot_list:
            return f"No open slots found for {provider} today. The system will look for the next available day."
            
        slot_count = len(slot_list)
        slots_str  = ", ".join(str(s) for s in slot_list[:3])
        note       = f" ({skipped})" if skipped else ""
        return (
            f"Successfully retrieved {slot_count} open slot(s) for {provider} on {date}{note}. "
            f"Earliest times include: {slots_str}. Presenting these options to the member."
        )

    if tool_name == "book_appointment":
        status = result.get("status", "")
        if status == "confirmed":
            prov = result.get("provider_name", result.get("provider", ""))
            date = result.get("date", result.get("appointment_date", ""))
            time = result.get("time", result.get("time_slot", ""))
            return f"✅ Appointment confirmed with {prov} on {date} at {time}. Session saved and the member is all set."
        if status == "blocked":
            reason = result.get("reason", "")
            if reason == "prior_auth_required":
                return "⛔ Booking blocked — prior auth not yet approved by Cigna. Showing imaging options for when it clears."
            if reason == "referral_required":
                return "⛔ Booking blocked — PCP referral required and not yet approved. Will book the moment the referral comes through."
            return f"⛔ Booking blocked: {result.get('message', '')[:120]}"
        if status == "conflict":
            return (
                f"⛔ Booking conflict — member already has an appointment with "
                f"{result.get('conflicting_provider', 'another provider')} at "
                f"{result.get('conflicting_time', 'the same time')}. "
                f"Tell the member and ask them to pick a different time slot."
            )
        return f"Booking result: {status}."

    if tool_name == "notify_provider":
        if result.get("sent"):
            notif_type = result.get("type", "notification")
            provider   = result.get("provider", "provider")
            return (
                f"✅ {notif_type.replace('_', ' ').title()} sent to {provider}'s office. "
                f"They will follow up with the insurance company directly."
            )
        return "Notification could not be sent — will retry or inform the member."

    if tool_name == "request_plan_change":
        status = result.get("status", "")
        new_plan = result.get("new_plan", "")
        if status == "submitted":
            return (
                f"✅ Plan change to '{new_plan}' submitted to Cigna for approval. "
                f"A Cigna representative will review and approve the request. "
                f"Member will be notified on next login once approved."
            )
        return f"Plan change result: {status}."

    return ""


# ── ADK Agent ─────────────────────────────────────────────────────────────────
_VERTEX_MODEL    = settings.LLM_MODEL or "gemini-2.0-flash"
_session_service = InMemorySessionService()
APP_NAME         = "adk"

# ── root_agent — required by ADK's agent_loader when mounted at /adk ─────────
# The ADK API server (POST /adk/run) looks for `root_agent` at module level.
# We expose a minimal placeholder agent here; the real per-user agents are
# created dynamically in _get_runner() and invoked via run_adk_agent_stream().
from google.genai import types as _genai_types
_STREAM_CONFIG = _genai_types.GenerateContentConfig(temperature=0.2)

root_agent = LlmAgent(
    name                   = "HealthcareProviderSearchAgent",
    model                  = _VERTEX_MODEL,
    description            = "Agentic healthcare provider search with booking and memory.",
    instruction            = "You are a healthcare concierge. Use the provided tools to help members.",
    generate_content_config= _STREAM_CONFIG,
    tools                  = [
        FunctionTool(find_providers),
        FunctionTool(notify_provider),
        FunctionTool(check_availability),
        FunctionTool(book_appointment),
        FunctionTool(request_plan_change),
        FunctionTool(cancel_appointment),
    ],
)


def _get_runner(user_id: str, travel_city: str = "", travel_state: str = "", member_state: dict | None = None) -> Runner:
    """Cached runner per user. Rebuilt after booking so new booking appears in system prompt."""
    runner_key = f"{user_id}|{travel_city}|{travel_state}"
    if runner_key not in _runners:
        agent = LlmAgent(
            name                   = "HealthcareProviderSearchAgent",
            model                  = _VERTEX_MODEL,
            description            = "Agentic healthcare provider search with booking and memory.",
            instruction            = _build_system_prompt(user_id, travel_city, travel_state, member_state=member_state),
            generate_content_config= _STREAM_CONFIG,
            tools                  = [
                FunctionTool(find_providers),
                FunctionTool(notify_provider),
                FunctionTool(check_availability),
                FunctionTool(book_appointment),
                FunctionTool(request_plan_change),
                FunctionTool(cancel_appointment),
            ],
        )
        _runners[runner_key] = Runner(
            agent           = agent,
            app_name        = APP_NAME,
            session_service = _session_service,
        )
    return _runners[runner_key]


# ── Public API ────────────────────────────────────────────────────────────────
async def run_adk_agent_stream(message: str, user_id: str, travel_city: str = "", travel_state: str = "", previous_plan: str = "", new_plan: str = "") -> AsyncIterator[dict]:
    history = storage.get_history(user_id)

    # Invalidate stale runner on new session so system prompt rebuilds fresh
    if user_id not in _adk_sessions:
        for k in [k for k in list(_runners.keys()) if k.startswith(f"{user_id}|")]:
            _runners.pop(k, None)

    # Also always rebuild runner on __session_start__ and __location_change__
    # so prompt changes take effect without requiring a backend restart.
    if message in ("__session_start__", "__location_change__", "__plan_change_greeting__"):
        for k in [k for k in list(_runners.keys()) if k.startswith(f"{user_id}|")]:
            _runners.pop(k, None)

    # ── Single storage read per request (shared by runner build + proactive block) ──
    _member_state_for_request = storage.get_member_state(user_id)

    runner = _get_runner(user_id, travel_city=travel_city, travel_state=travel_state, member_state=_member_state_for_request)

    history_lines = []
    for t in history[-20:]:
        role    = "user" if t["role"] == "user" else "assistant"
        content = t["content"]
        if role == "assistant" and len(content) > 300:
            content = content[:300] + "..."
        history_lines.append(f"{role}: {content}")

    # ── Build augmented message ───────────────────────────────────────────────
    if message == "__plan_change_greeting__":
        try:
            user = _users.get_user(user_id)
            # Read plan names from the plan_change file — source of truth for old/new plan names
            _pc_file = storage.read(f"plan_change/{user_id}.json") or {}
            previous_plan = _pc_file.get("previous_plan", previous_plan)
            new_plan = _pc_file.get("new_plan") or user.insurance_plan
        except Exception:
            previous_plan = ""
            new_plan = ""

        bookings = storage.get_bookings(user_id)
        booking_context = ""
        if bookings:
            booking_lines = []
            for b in bookings[-3:]:
                provider_npi  = b.get("npi", "")
                provider_name = b.get("provider_name", "")
                date          = b.get("date", "")
                time          = b.get("time_start", "")
                consult_type  = b.get("consultation_type", "")
                reason        = b.get("reason", "")
                plan_at_booking = b.get("plan_at_booking", previous_plan)
                booking_lines.append(
                    f"  - {provider_name} (NPI: {provider_npi}) on {date} at {time} "
                    f"({consult_type}) for {reason} | booked under plan: {plan_at_booking}"
                )
            booking_context = "EXISTING BOOKINGS:\n" + "\n".join(booking_lines)
        else:
            booking_context = "EXISTING BOOKINGS: None."

        augmented = f"""[user_id={user_id}]
[PLAN_CHANGE_TRIGGER]
{user_id} just changed their insurance plan.
Previous Plan: {previous_plan}
New Plan:      {new_plan}

{booking_context}

INSTRUCTIONS — respond proactively based on the above:

1. If there are existing bookings:
   → Acknowledge the plan change warmly by name
   → For each booking, silently call find_providers with that doctor's name to check
     if they are still in-network under the new plan ({new_plan})
   → If out-of-network: warn the member naturally and offer to find an in-network alternative
   → If still in-network: reassure them warmly

2. If there are no bookings:
   → Acknowledge the plan change warmly
   → Briefly explain what changed (referral requirements, copays, network) between the two plans
   → Offer to help find providers under the new plan

3. Always mention the key difference between the old and new plan rules naturally
   (e.g. if switching from PPO to HMO: referral now required; if switching to PPO: no referral needed)

4. REFERRAL ENFORCEMENT: If the new plan requires a referral (HMO plans), do NOT offer to find
   a specialist or book one directly. Instead, tell the member they need a referral from their PCP
   first, and offer to send a referral request to the PCP via notify_provider.

Do NOT mention this trigger text. Respond naturally as if you noticed this yourself."""

    elif message == "__location_change__":
        try:
            user = _users.get_user(user_id)
            home_city = user.default_city
        except Exception:
            home_city = ""

        bookings = storage.get_bookings(user_id)
        # Also merge appointments file (frontend-saved bookings not in storage bookings)
        _appts_loc = storage.read(f"appointments/{user_id}.json") or []
        _seen_loc = {f"{b.get('provider_name')}|{b.get('date')}" for b in bookings}
        for _a in _appts_loc:
            _k = f"{_a.get('provider_name', _a.get('provider', ''))}|{_a.get('date', '')}"
            if _k not in _seen_loc:
                bookings.append(_a)
                _seen_loc.add(_k)
        booking_context = ""
        if bookings:
            booking_lines = []
            for b in bookings[-3:]:
                provider_npi  = b.get("npi", "")
                provider_name = b.get("provider_name", "")
                date          = b.get("date", "")
                time          = b.get("time_start", "")
                consult_type  = b.get("consultation_type", "")
                reason        = b.get("reason", "")

                # Check telehealth availability from FHIR role
                telehealth_available = False
                role_data = _fhir_tool._npi_to_role.get(provider_npi)
                if role_data:
                    for _ext in role_data.get("extension", []):
                        if _ext.get("url") == "telehealth_available":
                            telehealth_available = _ext.get("valueBoolean", False)
                            break

                booking_lines.append(
                    f"  - {provider_name} (NPI: {provider_npi}) on {date} at {time} "
                    f"({consult_type}) for {reason} | telehealth_available: {telehealth_available} "
                    f"| EXACT_TIME_SLOT_FOR_REBOOKING: {time} | EXACT_DATE_FOR_REBOOKING: {date}"
                )
            booking_context = "UPCOMING BOOKINGS:\n" + "\n".join(booking_lines)
        else:
            booking_context = "UPCOMING BOOKINGS: None."

        # Get member's plan for HMO network warning
        try:
            _loc_user = _users.get_user(user_id)
            _loc_plan = _loc_user.insurance_plan
            _loc_plan_rules = _get_plan_rules(_loc_plan)
            _loc_requires_referral = _loc_plan_rules.get("requires_referral", False)
        except Exception:
            _loc_plan = ""
            _loc_requires_referral = False

        _hmo_warning = ""
        if _loc_requires_referral:
            _hmo_warning = f"""
HMO PLAN WARNING — IMPORTANT:
{user_id}'s plan ({_loc_plan}) is an HMO centered on {home_city}.
Doctors in {travel_city} are very likely OUT-OF-NETWORK.
When the member asks for a provider in {travel_city}:
  → Warn them warmly: "Heads up — your plan is based in {home_city}, so doctors in {travel_city} will likely
    be out-of-network, meaning higher costs out of pocket (OOP max: {_loc_plan_rules.get('oop_max', 'see plan')}).
    A telehealth call with your {home_city} PCP is often the most cost-effective option while travelling."
  → Then offer: 1) Telehealth with home PCP, OR 2) Local provider with OON cost warning.
  → If they confirm they want a local provider anyway → find_providers normally and flag OON clearly.
"""

        augmented = f"""[user_id={user_id}]
[LOCATION_CHANGE_TRIGGER]
{user_id} just changed their location from {home_city} to {travel_city}, {travel_state}.

{booking_context}
{_hmo_warning}
INSTRUCTIONS — respond proactively based on the above:

1. If there are bookings with consultation_type="In-Person" AND telehealth_available=true:
   → Greet the member warmly by first name
   → Ask: "I see you're now currently in {travel_city} — but you have an upcoming in-person
     appointment with [Dr. X] on [date]. Will you still be able to make it back to {home_city}
     by then?"
   → WAIT for their reply. Do NOT offer telehealth yet — let them answer first.
   → If they say YES they'll be back: say "Perfect — your appointment is all set then. Let me
     know if you need anything while you're in {travel_city}!" End the conversation naturally.
   → If they say NO they won't be back:
     FIRST CHECK: Does their NO message also mention rescheduling?
     (e.g. "reschedule", "move it", "push it back", "book it for later", "change the date")
     If YES → skip the telehealth question entirely and jump straight to the RESCHEDULE path in the continuity context.
     If NO reschedule intent:
     STOP — do NOT search for providers yet.
     Ask ONE question only: "Got it — would a telehealth video call work for
     you instead? [Dr. X] does offer telehealth, so we could keep the same time slot."
     WAIT for their answer before doing anything else.

     ONLY after they answer the telehealth question:
     If they say YES to telehealth: call book_appointment IMMEDIATELY with:
       - consultation_type="Telehealth"
       - provider_name = exact provider name from UPCOMING BOOKINGS above
       - npi = exact NPI from UPCOMING BOOKINGS above
       - time_slot = the EXACT_TIME_SLOT_FOR_REBOOKING value from UPCOMING BOOKINGS above
       - appointment_date = the EXACT_DATE_FOR_REBOOKING value from UPCOMING BOOKINGS above
       - reason = same reason as the original booking
       DO NOT call check_availability first. The slot is already confirmed — just rebook it as Telehealth.
       Confirm: "Done! I've switched your [date] appointment with [Dr. X] to a telehealth
       video call at [time]. You'll get a link before the appointment."
     If they say NO to telehealth (they prefer in-person): call find_providers with travel_city="{travel_city}"
     travel_state="{travel_state}" to find local providers near them. Use the `reason`
     field from UPCOMING BOOKINGS to determine the specialty. NEVER ask the member what
     the appointment was for. Mention clearly that these will be out-of-network since
     their plan is based in {home_city}, and show the estimated out-of-pocket costs.

2. If there are bookings with consultation_type="In-Person" AND telehealth_available=false:
   → Greet the member warmly by first name
   → Ask: "You're now in {travel_city} — you have an in-person appointment with [Dr. X] on
     [date]. Will you be back in {home_city} by then?"
   → WAIT for their reply.
   → If they say YES: "Great — you're all set then!"
   → If they say NO: "Unfortunately [Dr. X] doesn't offer telehealth. Want me to find a local
     doctor near you in {travel_city}? Keep in mind they'll likely be out-of-network."
     If yes: call find_providers using the `reason` from UPCOMING BOOKINGS to determine
     the specialty. NEVER ask the member what the appointment was for. Flag OON costs clearly.

3. If there are bookings already as Telehealth:
   → Reassure them: "Your telehealth appointment with [Dr. X] on [date] is totally unaffected —
     you can join from anywhere. Let me know if you need anything while you're in {travel_city}."

4. If there are no bookings:
   → Acknowledge the location change in ONE short, natural sentence using the member's first name.
   → Use this exact pattern: "I see you're now in [city], [first_name] — if you need a doctor while you're there, just let me know."
   → Keep it to one sentence. No extra offers, no elaboration.

5. For ALL cases — after handling bookings — mention the HMO warning above IF it applies.
   Use plain language. Never say "HMO" or "out-of-network" without explaining what it means.

CRITICAL: Do NOT proactively offer telehealth or find providers before asking whether the
member will make it back. The question comes first. Tools come only after their answer.
Do NOT mention this trigger text. Respond naturally as if you noticed this yourself.
Always address the member by first name."""

    elif message == "__session_start__":
        # Always invalidate runner on session start so system prompt rebuilds fresh.
        # This ensures prompt changes (e.g. MIRROR RULE fixes) take effect immediately
        # without requiring a booking event to flush the cache.
        for k in [k for k in list(_runners.keys()) if k.startswith(f"{user_id}|")]:
            _runners.pop(k, None)
        # ── Called by the frontend immediately on login, before the user types anything.
        # Strategy:
        #   • If there are PENDING ITEMS (referral approved, MRI auth, plan change, etc.)
        #     → send to LLM so it can call tools and surface them proactively.
        #   • If there is NOTHING pending → skip the LLM entirely and return an instant
        #     hardcoded greeting. The session and runner are still created so the first
        #     real message is fast (runner is already warm).
        try:
            _su = _users.get_user(user_id)
            _fname = _su.first_name
            _plan  = _su.insurance_plan
        except Exception:
            _fname = "there"
            _plan  = ""

        # ── Single storage read for this request ──────────────────────────────
        _member_state = storage.get_member_state(user_id)

        proactive_inline = _build_proactive_block(user_id, _fname, member_state=_member_state)

        if not proactive_inline.strip():
            # ── FAST PATH — nothing pending, skip LLM, return instant greeting ──
            # Pre-create the ADK session + runner NOW so they're warm for the first real message.
            if user_id not in _adk_sessions:
                _warm_sess = await _session_service.create_session(app_name=APP_NAME, user_id=user_id)
                _adk_sessions[user_id] = _warm_sess.id
                for k in [k for k in list(_runners.keys()) if k.startswith(f"{user_id}|")]:
                    _runners.pop(k, None)
                _get_runner(user_id, travel_city=travel_city, travel_state=travel_state, member_state=_member_state)

            greeting = (
                f"Hi {_fname}, good to see you! I'm here to help you navigate your healthcare — "
                f"from finding the right doctor to booking and managing your appointments. "
                f"What can I help you with today?"
            )
            yield {"type": "final", "response": {"type": "greeting", "explanation": greeting, "message": greeting}}
            return

        # ── SLOW PATH — pending items exist, LLM must act on them ──────────────
        # If MRI/prescription + prior-auth items exist, enforce a friendly, deterministic
        # opening message. This ensures the first assistant message consistently
        # includes a greeting, appointment reference, status update, timeline, and
        # an offer to find imaging centers. For 'none' status we also trigger a
        # notify_provider reminder before telling the member.
        _proactive_shown.add(user_id)   # mark so the else-branch won't re-run this

        # Inspect member files for MRI/prior-auth and preference
        try:
            _mri = storage.get_mri_prescription(user_id) or {}
            _pa  = storage.get_prior_auth(user_id) or {}
            # Read preferences directly from storage to ensure we pick up the
            # most recent saved preference even when member_state snapshots
            # omit it.
            _prefs = storage.read(f"preferences/{user_id}.json") or {}
            _pref = (_prefs or {}).get("preferred_imaging_provider") or (_prefs or {}).get("preferred_provider") or {}
        except Exception:
            _mri = {}
            _pa = {}
            _pref = {}

        mri_present = bool(_has_mri_prescription(_mri))
        pa_status = (_pa or {}).get("status", "none")

        # If there's an MRI prescription and it's relevant, generate deterministic reply
        if mri_present and ("MRI_PENDING_AUTH" in proactive_inline or "MRI_AUTH_PENDING" in proactive_inline or "MRI_AUTH_APPROVED" in proactive_inline or "MRI_VISIT_DONE_AUTH_MISSING" in proactive_inline):
            prescribed_by = _mri.get("prescribed_by") or {}
            doc_name = prescribed_by.get("name") if isinstance(prescribed_by, dict) else str(prescribed_by or "your specialist")
            body_part = _mri.get("body_part") or _mri.get("procedure") or "MRI"
            presc_date = _mri.get("prescribed_date") or "recently"

            # Build the friendly assistant text
            if pa_status == "none":
                # Send a notify_provider reminder then inform the member
                try:
                    notify_provider(user_id=user_id, provider_name=doc_name, notification_type="prior_auth_request", message=f"Please submit prior auth for {body_part} for member {user_id}.")
                except Exception:
                    pass
                assistant_text = (
                    f"Hello {_fname}, I see you visited {doc_name} on {presc_date} for {body_part} after your fall. "
                    f"Your MRI prescription is ready, but {doc_name}'s office has not yet sent the approval request to Cigna. "
                    f"I've just sent {doc_name}'s office a reminder to submit the approval request to Cigna — these usually clear in 2-5 business days. "
                    f"The moment it comes through, I'll get your scan booked. Would you like me to find imaging centers near you so we're ready?"
                )
                # Persist the deterministic assistant turn, then return it (no provider cards)
                try:
                    storage.save_turn(user_id, "assistant", assistant_text)
                except Exception:
                    pass
                yield {"type": "final", "response": {"type": "notification", "message": assistant_text, "explanation": assistant_text}}
                return

            if pa_status == "pending":
                pa_ref = _pa.get("auth_reference_number") or ""
                pa_date = _pa.get("submitted_date") or ""
                assistant_text = (
                    f"Hello {_fname}, I see you visited {doc_name} on {presc_date} for {body_part}. "
                    f"{_ensure_dr_prefix(doc_name)} submitted the approval request to Cigna on {pa_date} (Ref# {pa_ref}); Cigna is reviewing it now and these usually clear in 2-5 business days. "
                    f"Would you like me to find imaging centers near you so you're ready the moment it comes through?"
                )
                try:
                    storage.save_turn(user_id, "assistant", assistant_text)
                except Exception:
                    pass
                yield {"type": "final", "response": {"type": "notification", "message": assistant_text, "explanation": assistant_text}}
                return

            if pa_status == "approved":
                pa_ref = _pa.get("auth_reference_number") or ""
                pa_valid = _pa.get("valid_through") or ""
                # If a preferred provider exists, proactively return that provider's card
                if _pref and (_pref.get("provider_name") or _pref.get("npi")):
                    try:
                        # Fetch provider by name to return as provider_results
                        prov_res = find_providers(user_id=user_id, specialty="Radiology", doctor_name=_pref.get("provider_name") or "", travel_city=travel_city, travel_state=travel_state)
                        providers = prov_res.get("providers") if isinstance(prov_res, dict) else []
                    except Exception:
                        providers = []

                    # If the provider lookup returned no results, synthesize a provider
                    # from the stored preference so the frontend can render a card.
                    if not providers and _pref and (_pref.get("provider_name") or _pref.get("npi")):
                        providers = [{
                            "name": _pref.get("provider_name") or _pref.get("name") or "Preferred Provider",
                            "npi": _pref.get("npi", ""),
                            "address": _pref.get("address", ""),
                            "city": _pref.get("city", ""),
                            "specialty": _pref.get("specialty", "Radiology"),
                            "status": "in-network",
                        }]
                    assistant_text = (
                        f"Hello {_fname}, I see you visited {doc_name} on {presc_date} for {body_part}. "
                        f"Good news: Cigna approved your prior authorization for the {body_part} MRI (Ref# {pa_ref}, valid through {pa_valid}). "
                        f"I can go ahead and book your scan with your preferred provider {(_pref.get('provider_name') or '').strip()} — or shall I find other centers and get it scheduled?"
                    )
                    try:
                        storage.save_turn(user_id, "assistant", assistant_text)
                    except Exception:
                        pass
                    return_obj = {
                        "type": "provider_results",
                        "providers": providers or [],
                        "message": assistant_text,
                        "explanation": assistant_text,
                    }
                    yield {"type": "final", "response": return_obj}
                    return
                else:
                    # No stored preference — DO NOT attempt to auto-infer a preferred provider.
                    # Instead, ask the member explicitly to confirm a preferred imaging provider
                    # or offer to find imaging centers. This avoids false-positive inference.
                    assistant_text = (
                        f"Hello {_fname}, I see you visited {doc_name} on {presc_date} for {body_part}. "
                        f"Good news: Cigna approved your prior authorization for the {body_part} MRI (Ref# {pa_ref}, valid through {pa_valid}). "
                        "Do you already have a preferred imaging provider you'd like me to book with, or would you like me to find imaging centers near you so we can schedule the scan?"
                    )
                    try:
                        storage.save_turn(user_id, "assistant", assistant_text)
                    except Exception:
                        pass
                    yield {"type": "final", "response": {"type": "notification", "message": assistant_text, "explanation": assistant_text}}
                    return

        # Fallback: let the LLM handle the slow path if no deterministic MRI case applied
        augmented = (
            f"[user_id={user_id}]\n"
            f"[SESSION_OPEN — {_fname} just logged in. No message typed yet.]\n\n"
            f"You have already reviewed {_fname}'s file before they arrived. "
            f"The following pending items require IMMEDIATE action in your opening message. "
            f"Do NOT say 'Welcome back' and wait. Do NOT list items robotically. "
            f"Act on them right now — call the tools, deliver the outcome, speak like a "
            f"knowledgeable friend who already knows everything about {_fname}.\n"
            + proactive_inline
        )

        if travel_city:
            augmented += f"\n[{_fname} is currently in {travel_city}, {travel_state}.]"

        if history_lines:
            augmented += "\n\n[Previous sessions summary]\n" + "\n".join(history_lines[-6:])

    else:
        augmented = f"[user_id={user_id}]\n{message}"
        if travel_city:
            augmented += f"\n[TRAVEL_OVERRIDE: {user_id} is currently in {travel_city}, {travel_state}. Always pass travel_city='{travel_city}' and travel_state='{travel_state}' to find_providers for this entire session.]"

        # ── Plan change confirmation direct tool call (mirrors location change) ──
        # When the member confirms a plan the agent just recommended,
        # call request_plan_change directly in Python without going through LLM.
        # This mirrors the telehealth conversion fix in location change scenario.
        if history:
            # Use the in-memory history (same source as the rest of this branch) so the
            # last agent message is always the most recent turn — not a stale file read.
            _last_agent_msg_pc = next(
                (t["content"] for t in reversed(history) if t["role"] == "assistant"), ""
            )

            _is_plan_followup = (
                "would you like me to switch you over" in _last_agent_msg_pc.lower()
                or "want me to switch you" in _last_agent_msg_pc.lower()
                or "switch you over to" in _last_agent_msg_pc.lower()
                or "just to confirm" in _last_agent_msg_pc.lower()
                or "shall i switch" in _last_agent_msg_pc.lower()
                or "like to switch to" in _last_agent_msg_pc.lower()
                or "switch you to" in _last_agent_msg_pc.lower()
                or "would you like to switch to" in _last_agent_msg_pc.lower()
            )
            if _is_plan_followup:
                # Check if plan change already exists in storage
                _existing_pc = storage.read(f"plan_change/{user_id}.json")
                if _existing_pc and not _existing_pc.get("payer_decision"):
                    # Already submitted, just confirm to member
                    final_text = (
                        f"I've already submitted your request to switch to {_existing_pc.get('new_plan')} "
                        f"to Cigna for approval. A representative will review it — once approved, "
                        f"your new plan takes effect immediately."
                    )
                    storage.save_turn(user_id, "user", message)
                    storage.save_turn(user_id, "assistant", final_text)
                    yield {"type": "text", "text": final_text}
                    yield {"type": "final", "response": {"type": "chat", "explanation": final_text}}
                    return

                # Detect plan name from last agent message
                # Sort by key length descending so longer/more-specific names match
                # before shorter ones that are substrings (e.g. "cigna true choice"
                # must not match before "cigna true choice access").
                _detected_plan_name = ''
                _detected_plan_id   = ''
                for _plan_key, (_plan_id, _plan_display) in sorted(_PLAN_ID_MAP.items(), key=lambda x: len(x[0]), reverse=True):
                    if _plan_key in _last_agent_msg_pc.lower():
                        _detected_plan_name = _plan_display
                        _detected_plan_id   = _plan_id
                        break

                # Check if member's message is a positive confirmation
                if _detected_plan_name and _detected_plan_id:
                    _msg_lower = message.strip().lower()
                    _is_positive = any(
                        w in _msg_lower for w in [
                            "yes", "ok", "sure", "yeah", "yep", "go ahead", "do it",
                            "make it", "switch", "change", "convert", "sounds good", "great",
                            "of course", "absolutely", "alright", "let's do it"
                        ]
                    )

                    # Count how many distinct plan names appear in the last agent message.
                    # If more than one plan was offered and the member's reply is a bare
                    # positive ("yes", "ok", etc.) without naming a specific plan, the
                    # intent is ambiguous — fall through to LLM to ask for clarification.
                    _plans_in_msg = sum(
                        1 for pk in _PLAN_ID_MAP if pk in _last_agent_msg_pc.lower()
                    )
                    _member_named_plan = any(
                        pk in _msg_lower for pk in _PLAN_ID_MAP
                    )
                    if _plans_in_msg > 1 and not _member_named_plan:
                        _is_positive = False  # ambiguous — let LLM ask which plan

                    if _is_positive:
                        # DIRECT TOOL CALL - bypass LLM (mirrors location change telehealth conversion)
                        try:
                            pc_result = request_plan_change(
                                user_id=user_id,
                                new_plan=_detected_plan_name,
                                new_plan_id=_detected_plan_id
                            )

                            if pc_result.get("status") == "submitted":
                                try:
                                    _pc_user = _users.get_user(user_id)
                                    _pc_fname = _pc_user.first_name
                                except Exception:
                                    _pc_fname = ""

                                final_text = (
                                    f"Done, {_pc_fname}! I've submitted your request to switch to **{_detected_plan_name}** "
                                    f"to Cigna for approval. A representative will review it — once approved, "
                                    f"your new plan takes effect immediately and I'll let you know the moment "
                                    f"you log back in. Please note that doctors in-network under your previous "
                                    f"plan may not be in-network under your new plan."
                                )

                                storage.save_turn(user_id, "user", message)
                                storage.save_turn(user_id, "assistant", final_text)

                                yield {"type": "text", "text": final_text}
                                yield {
                                    "type": "final",
                                    "response": {
                                        "type":    "booking_confirmation",
                                        "booking": pc_result,
                                        "message": final_text,
                                    },
                                }
                                return
                        except Exception:
                            # If direct call fails, fall through to LLM path
                            pass

                    if _detected_plan_name:
                        augmented += (
                            f"\n\n[PLAN_CHANGE_CONTEXT]"
                            f"\nThe member is confirming the plan change you just recommended."
                            f"\nRecommended plan: {_detected_plan_name}"
                            f"\nPlan ID: {_detected_plan_id}"
                            f"\nCall request_plan_change IMMEDIATELY with:"
                            f"\n  - user_id = {user_id}"
                            f"\n  - new_plan = \"{_detected_plan_name}\""
                            f"\n  - new_plan_id = \"{_detected_plan_id}\""
                            f"\nDo NOT ask for confirmation again. Do NOT repeat the plan details. Call the tool now."
                        )
        # ───────────────────────────────────────────────────────────────────────

        # ── Location-change telehealth confirmation — direct Python bypass ────
        # When the last agent message asked "would a telehealth video call work" and
        # the member says yes, call book_appointment directly in Python without the LLM.
        # This is the same pattern as the plan-change confirmation bypass and prevents
        # the LLM from producing an empty final_text on this single-word response.
        if travel_city and history:
            _last_agent_msg_tele = next(
                (t["content"] for t in reversed(history) if t["role"] == "assistant"), ""
            )
            _is_tele_confirm_q = (
                "telehealth video call work" in _last_agent_msg_tele.lower()
                or "would a telehealth" in _last_agent_msg_tele.lower()
                or "offer telehealth, so we could keep" in _last_agent_msg_tele.lower()
                or "does offer telehealth" in _last_agent_msg_tele.lower()
            )
            _msg_lower_tele = message.strip().lower()
            _is_yes_tele = any(
                w in _msg_lower_tele for w in [
                    "yes", "ok", "sure", "yeah", "yep", "please", "go ahead",
                    "sounds good", "great", "of course", "absolutely", "alright",
                    "yes please", "do it", "let's do it",
                ]
            )
            if _is_tele_confirm_q and _is_yes_tele:
                # Direct bypass: find the in-person booking and rebook as Telehealth
                try:
                    _bks_tele = storage.get_bookings(user_id) or []
                    _appts_tele = storage.read(f"appointments/{user_id}.json") or []
                    _seen_tele = {f"{b.get('provider_name')}|{b.get('date')}" for b in _bks_tele}
                    for _a in _appts_tele:
                        _k = f"{_a.get('provider_name', _a.get('provider', ''))}|{_a.get('date', '')}"
                        if _k not in _seen_tele:
                            _bks_tele.append(_a)
                            _seen_tele.add(_k)
                    _ip_bk = next(
                        (b for b in reversed(_bks_tele)
                         if (b.get("consultation_type") or "").lower() == "in-person"
                         and b.get("status") != "completed"),
                        None
                    )
                    if _ip_bk:
                        _tele_result = book_appointment(
                            user_id=user_id,
                            npi=_ip_bk.get("npi", ""),
                            provider_name=_ip_bk.get("provider_name", ""),
                            time_slot=_ip_bk.get("time_start", ""),
                            consultation_type="Telehealth",
                            appointment_date=_ip_bk.get("date", ""),
                            reason=_ip_bk.get("reason", ""),
                        )
                        if _tele_result.get("status") == "confirmed":
                            _prov_name = _tele_result.get("provider_name", _ip_bk.get("provider_name", "your doctor"))
                            _appt_date = _tele_result.get("date", _ip_bk.get("date", ""))
                            _appt_time = _tele_result.get("time_start", _ip_bk.get("time_start", ""))
                            try:
                                _tele_user = _users.get_user(user_id)
                                _tele_fname = _tele_user.first_name
                            except Exception:
                                _tele_fname = ""
                            final_text = (
                                f"Done, {_tele_fname}! I've switched your **{_appt_date}** appointment "
                                f"with **{_prov_name}** to a telehealth video call at **{_appt_time}**. "
                                f"You'll receive a link before the appointment."
                            )
                            storage.save_turn(user_id, "user", message)
                            storage.save_turn(user_id, "assistant", final_text)
                            yield {"type": "text", "text": final_text}
                            yield {
                                "type": "final",
                                "response": {
                                    "type":    "booking_confirmation",
                                    "booking": _tele_result,
                                    "message": final_text,
                                },
                            }
                            return
                except Exception:
                    pass  # fall through to LLM path if direct call fails

        # ── Location-change conversation continuity ───────────────────────────
        # When the member replies to the location-change greeting (e.g. "no, I'll be staying here"),
        # the agent needs context about the ongoing flow. Inject the booking + travel context so
        # the LLM can continue the conversation naturally (ask about telehealth, find local providers, etc.).
        if travel_city and history:
            _last_agent_msg = next(
                (t["content"] for t in reversed(history) if t["role"] == "assistant"), ""
            )
            _is_location_followup = (
                "make it back" in _last_agent_msg.lower()
                or "will you still be able" in _last_agent_msg.lower()
                or "you're now in" in _last_agent_msg.lower()
                or "currently in" in _last_agent_msg.lower()
                or "telehealth video call work" in _last_agent_msg.lower()
                or "would a telehealth" in _last_agent_msg.lower()
                or "offer telehealth" in _last_agent_msg.lower()
                or "keep the same time slot" in _last_agent_msg.lower()
            )
            if _is_location_followup:
                try:
                    _bks = storage.get_bookings(user_id) or []
                    # Also check appointments file (frontend-saved bookings)
                    _appts = storage.read(f"appointments/{user_id}.json") or []
                    # Merge both, deduplicate by provider+date, storage bookings take priority
                    _seen_keys = {f"{b.get('provider_name')}|{b.get('date')}" for b in _bks}
                    for _a in _appts:
                        _key = f"{_a.get('provider_name', _a.get('provider', ''))}|{_a.get('date', '')}"
                        if _key not in _seen_keys:
                            _bks.append(_a)
                            _seen_keys.add(_key)
                    _ip_booking = next(
                        (b for b in reversed(_bks)
                         if (b.get("consultation_type") or "").lower() == "in-person"
                         and b.get("status") != "completed"),
                        None
                    )
                    if _ip_booking:
                        _tele_avail = False
                        _role_data = _fhir_tool._npi_to_role.get(_ip_booking.get("npi", ""))
                        if _role_data:
                            for _ext in _role_data.get("extension", []):
                                if _ext.get("url") == "telehealth_available":
                                    _tele_avail = _ext.get("valueBoolean", False)
                                    break
                        try:
                            _loc_user = _users.get_user(user_id)
                            _home_city = _loc_user.default_city
                            _plan_name = _loc_user.insurance_plan
                            _oop_max   = _get_plan_rules(_plan_name).get("oop_max", "see plan")
                        except Exception:
                            _home_city = ""
                            _oop_max   = "see plan"
                        # Derive specialty from booking reason for in-person provider search
                        _booking_reason = (_ip_booking.get("reason") or "").lower()
                        _REASON_TO_SPECIALTY = {
                            "rash": "Dermatology", "skin": "Dermatology", "eczema": "Dermatology",
                            "heart": "Cardiology", "chest": "Cardiology", "cardiac": "Cardiology",
                            "knee": "Orthopaedic Surgery", "back": "Orthopaedic Surgery", "joint": "Orthopaedic Surgery",
                            "stomach": "Gastroenterology", "gut": "Gastroenterology", "bowel": "Gastroenterology",
                            "headache": "Neurology", "migraine": "Neurology", "neuro": "Neurology",
                            "eye": "Ophthalmology", "vision": "Ophthalmology",
                            "ear": "Otolaryngology", "throat": "Otolaryngology",
                            "urine": "Urology", "bladder": "Urology",
                            "anxiety": "Psychiatry", "depression": "Psychiatry", "mental": "Psychiatry",
                        }
                        _inferred_specialty = "Dermatology"  # default fallback
                        for _kw, _sp in _REASON_TO_SPECIALTY.items():
                            if _kw in _booking_reason:
                                _inferred_specialty = _sp
                                break
                        augmented += (
                            f"\n\n[LOCATION_CHANGE_CONTEXT]"
                            f"\nThe member is responding within the location-change conversation flow."
                            f"\nThey are currently in {travel_city}, {travel_state} (home: {_home_city})."
                            f"\nUpcoming booking: {_ip_booking.get('provider_name')} on {_ip_booking.get('date')} at {_ip_booking.get('time_start')}"
                            f" ({_ip_booking.get('consultation_type')}) for {_ip_booking.get('reason', '')}."
                            f"\nNPI: {_ip_booking.get('npi', '')} | telehealth_available: {_tele_avail}"
                            f"\nInferred specialty from booking reason: {_inferred_specialty}"
                            f"\nOOP max for member's plan: {_oop_max}"
                            f"\n"
                            f"\nBRANCHING RULES — FOLLOW STRICTLY IN ORDER:"
                            f"\n"
                            f"\n  STEP A — Member just said NO (they won't make it back):"
                            f"\n    → FIRST CHECK: Does their message ALSO contain a reschedule request?"
                            f"\n      (e.g. 'reschedule', 'move it', 'push it back', 'change the date', 'book it for later')"
                            f"\n      If YES → skip the telehealth question entirely and go straight to STEP B RESCHEDULE below."
                            f"\n    → If NO reschedule intent: STOP. Do NOT search for providers yet."
                            f"\n    → If telehealth_available=True: ask ONE question ONLY:"
                            f"\n      'Got it — would a telehealth video call work for you instead? {_ip_booking.get('provider_name', 'Your doctor')} does offer telehealth, so we could keep the same time slot.'"
                            f"\n    → If telehealth_available=False: ask ONE question ONLY:"
                            f"\n      'Unfortunately {_ip_booking.get('provider_name', 'your doctor')} doesn't offer telehealth. Would you like me to find a local in-person doctor near you in {travel_city}?'"
                            f"\n    → WAIT for their answer. Do NOT call find_providers yet."
                            f"\n"
                            f"\n  STEP B — Member answered the telehealth question:"
                            f"\n  IF member says yes to telehealth: call book_appointment IMMEDIATELY with:"
                            f"\n    - npi={_ip_booking.get('npi', '')}, provider_name={_ip_booking.get('provider_name')}"
                            f"\n    - appointment_date={_ip_booking.get('date')}, time_slot={_ip_booking.get('time_start')}"
                            f"\n    - consultation_type=Telehealth, reason={_ip_booking.get('reason', '')}"
                            f"\n    DO NOT call check_availability. Confirm: 'Done! Switched your {_ip_booking.get('date')} appointment with {_ip_booking.get('provider_name')} to a telehealth video call at {_ip_booking.get('time_start')}. You'll get a link before the appointment.'"
                            f"\n  IF member declines telehealth or says they want in-person:"
                            f"\n    → call find_providers(specialty='{_inferred_specialty}', travel_city='{travel_city}', travel_state='{travel_state}', user_id=user_id)"
                            f"\n    → If find_providers returns oon_fallback=False (in-network found):"
                            f"\n        Show providers naturally: 'I found in-network {_inferred_specialty.lower()} doctors near {travel_city} for your {_ip_booking.get('reason', 'appointment')}.'"
                            f"\n    → If find_providers returns oon_fallback=True (no in-network):"
                            f"\n        Say: 'I wasn't able to find any in-network {_inferred_specialty.lower()} doctors near {travel_city} for your {_ip_booking.get('reason', 'appointment')}. These are out-of-network options — your out-of-pocket cost would be up to {_oop_max}.' Then show the providers."
                            f"\n    → After find_providers, call check_availability on the top_pick, then present normally."
                            f"\n  IF member says they WILL be back (YES): reassure them and close naturally."
                            f"\n  IF member asks to RESCHEDULE (e.g. 'can you reschedule it to 1 week later', 'move it a week', 'push it back a week'):"
                            f"\n    → call check_availability(npi={_ip_booking.get('npi', '')}, provider_name={_ip_booking.get('provider_name')}, appointment_date='1 week from {_ip_booking.get('date')}')"
                            f"\n    → Present the first available slot on or near that date: 'I have [time] on [date] with {_ip_booking.get('provider_name')} — want me to reschedule your {_ip_booking.get('date')} appointment to that?'"
                            f"\n    → If member confirms (YES): call book_appointment with the new slot (consultation_type={_ip_booking.get('consultation_type')}, reason={_ip_booking.get('reason', '')}) AND THEN call cancel_appointment(user_id={user_id}, provider_name={_ip_booking.get('provider_name')}, appointment_date={_ip_booking.get('date')})"
                            f"\n    → Confirm: 'Done! Rescheduled your {_ip_booking.get('date')} appointment to [new date] at [new time]. The original appointment has been cancelled.'"
                        )
                except Exception:
                    pass

        # ── Telehealth conversion context injection ───────────────────────────
        # Removed hardcoded confirm-word detection — the LLM reads intent naturally
        # from [LOCATION_CHANGE_CONTEXT] which covers both YES and NO branches.
        # ─────────────────────────────────────────────────────────────────────

        # ── Symptom summary injection ────────────────────────────────────────────────
        # When the member has answered clarifying questions and this is their final
        # symptom answer, inject a summary of the full symptom exchange so the LLM
        # has everything in one place when writing the empathy + reasoning sentence.
        # Detect: history has 2+ assistant clarifying questions before this message.
        _clarifying_turns = [
            t for t in history[-6:]
            if t["role"] == "assistant" and "?" in t["content"]
            and len(t["content"]) < 300  # short = clarifying question, not a full response
        ]
        if len(_clarifying_turns) >= 2 and len(message.split()) < 30:
            # Build symptom summary from the Q&A pairs
            _symptom_lines = []
            _recent = history[-8:]
            for i, t in enumerate(_recent):
                if t["role"] == "assistant" and "?" in t["content"] and len(t["content"]) < 300:
                    _q = t["content"].strip()
                    # Find the member's answer (next user turn)
                    if i + 1 < len(_recent) and _recent[i + 1]["role"] == "user":
                        _a = _recent[i + 1]["content"].strip()
                        _symptom_lines.append(f"  Q: {_q}\n  A: {_a}")
            if _symptom_lines:
                _summary = "\n".join(_symptom_lines)
                augmented += (
                    f"\n\n[SYMPTOM SUMMARY — you have now gathered enough information from {len(_symptom_lines)} clarifying question(s). "
                    f"Use this to write a specific, warm empathy + reasoning sentence]\n"
                    f"The member has answered these clarifying questions:\n{_summary}\n"
                    f"Current answer: {message}\n"
                    f"Now act: identify the specialty, write the 5-step response (empathy → reasoning → plan → providers → CTA), then call find_providers. "
                    f"Do NOT ask any more clarifying questions — you have enough information.]"
                )
        _is_new_session = user_id not in _adk_sessions
        if _is_new_session and user_id not in _proactive_shown:
            try:
                _proactive_user = _users.get_user(user_id)
                _proactive_fname = _proactive_user.first_name
            except Exception:
                _proactive_fname = ""
            proactive_inline = _build_proactive_block(user_id, _proactive_fname, member_state=_member_state_for_request)
            if proactive_inline.strip():
                proactive_prefix = (
                    "[SESSION_START — READ THIS BEFORE PROCESSING THE MEMBER'S MESSAGE BELOW]\n"
                    "You have already reviewed this member's file BEFORE they logged in.\n"
                    "You MUST address ALL pending items in your VERY FIRST response.\n"
                    "Do NOT greet generically and wait. Do NOT answer only their question.\n"
                    "You are a proactive healthcare concierge who spotted these items on file already.\n"
                    "IMPORTANT: For ALL pending items — REPORT the status and ASK what they'd like to do next. "
                    "Do NOT call any tools automatically. Do NOT run find_providers or check_availability on your own. "
                    "Simply tell the member what you found and ask: 'Would you like me to help with [action]?' "
                    "Only call tools AFTER the member explicitly replies and asks you to proceed.\n"
                    + proactive_inline
                    + "\n\n[MEMBER'S FIRST MESSAGE — handle this alongside the above pending items]\n"
                )
                augmented = proactive_prefix + augmented
                _proactive_shown.add(user_id)
            else:
                augmented = (
                    "[SESSION_START: No pending items. Greet the member warmly by name and handle their request.]\n\n"
                    + augmented
                )
        # Only inject last 6 turns of history on the very first typed message
        # (before ADK session has any context). After that ADK tracks it natively.
        if history_lines and _is_new_session:
            augmented += "\n\n[Conversation so far]\n" + "\n".join(history_lines[-6:])

    adk_session_id = _adk_sessions.get(user_id)
    if not adk_session_id:
        sess           = await _session_service.create_session(app_name=APP_NAME, user_id=user_id)
        adk_session_id = sess.id
        _adk_sessions[user_id] = adk_session_id
        # New session = new login — invalidate runner so system prompt rebuilds with latest plan
        for k in [k for k in list(_runners.keys()) if k.startswith(f"{user_id}|")]:
            _runners.pop(k, None)


    user_content = Content(role="user", parts=[Part(text=augmented)])

    state = {
        "providers":     [],
        "booking":       None,
        "availability":  None,
        "emergency":     False,
        "partial_texts": [],
        "_tool_calls":   [],
        "_tool_results": [],
    }

    try:
        async with asyncio.timeout(120):
          async for event in runner.run_async(
            user_id=user_id, session_id=adk_session_id, new_message=user_content,
          ):
            if not event.is_final_response() and event.content and event.content.parts:
                partial = "".join(
                    p.text for p in event.content.parts if hasattr(p, "text") and p.text
                )
                if partial.strip():
                    state["partial_texts"].append(partial)
                    yield {"type": "partial_text", "text": partial}

            if event.get_function_calls():
                for fc in event.get_function_calls():
                    labels = {
                        "find_providers":      "🏥 Finding providers…",
                        "notify_provider":     "📨 Notifying provider's office…",
                        "check_availability":  "📅 Checking availability…",
                        "book_appointment":    "✅ Booking appointment…",
                        "request_plan_change": "🔄 Updating insurance plan…",
                    }
                    args = dict(fc.args) if fc.args else {}

                    # Track tool call inputs so tool results can reference them
                    state.setdefault("_tool_calls", []).append({"tool": fc.name, "input": args})

                    # ── Rich reasoning: WHY is the agent calling this tool? ──────
                    thought = _build_tool_thought(fc.name, args, state)

                    yield {
                        "type":   "tool_call",
                        "tool":   fc.name,
                        "input":  args,
                        "label":  labels.get(fc.name, fc.name),
                        "thought": thought,
                    }

            if event.get_function_responses():
                for fr in event.get_function_responses():
                    raw = fr.response
                    if isinstance(raw, str):
                        try:    raw = json.loads(raw)
                        except Exception:
                            try:
                                raw = ast.literal_eval(raw)
                            except Exception:
                                raw = {"_raw": raw}
                    if not isinstance(raw, dict):
                        raw = {"_data": raw}

                    # ── Inject reasoning context into find_providers result ──────
                    # This tells the LLM exactly what it inferred and why, so it
                    # echoes it back naturally in the final response text.
                    if fr.name == "find_providers" and not raw.get("error") and not raw.get("emergency"):
                        _fp_args     = next((e.get("input", {}) for e in reversed(state.get("_tool_calls", []))
                                             if e.get("tool") == "find_providers"), {})
                        _specialty   = _fp_args.get("specialty", raw.get("specialty", ""))
                        _urgency     = _fp_args.get("urgency", "routine")
                        _city        = raw.get("searched_city", "")
                        _oon         = raw.get("oon_fallback", False)
                        _is_travel   = raw.get("is_travel_search", False)
                        _rr          = raw.get("routing_reason", "")
                        
                        # Generate dynamic reasoning context based on what happened
                        _history_matches = []
                        if state.get("memory"):
                            # Check if the specialty or symptom matches anything in medical history
                            _conds = state["memory"].get("conditions", [])
                            for c in _conds:
                                if any(t in c.lower() for t in _specialty.lower().split()):
                                    _history_matches.append(c)

                        _reasoning = f"[REASONING_CONTEXT: You mapped the member's symptom to '{_specialty}'"
                        
                        if _history_matches:
                            _reasoning += f" because it matches their medical history of {', '.join(_history_matches)}"
                        elif _rr:
                            _reasoning += f" because of {_rr}"
                        
                        if _urgency == "urgent":
                            _reasoning += ", treated as URGENT"
                            
                        # Add routing justification if it's a specialist
                        if _specialty.lower() not in ("primary care", "family medicine", "internal medicine"):
                            _reasoning += ", routing directly to a specialist based on symptom mechanism and duration"
                        else:
                            _reasoning += ". PCP evaluation is appropriate for new short-duration or unclear symptoms"
                            
                        if _is_travel:
                            _reasoning += f", searched in travel city '{_city}' (not home city)"
                        if _oon:
                            _reasoning += ", no in-network providers found so showing out-of-network options"
                            
                        _reasoning += ". Your response MUST open with a plain-language sentence explaining this reasoning to the member before showing any providers or slots.]"
                        raw["_reasoning_context"] = _reasoning

                    if fr.name == "find_providers":
                        state.setdefault("_tool_results", []).append({"tool": fr.name, **raw})
                        if raw.get("emergency"):
                            state["emergency"] = True
                        if raw.get("providers"):
                            # Normalize provider entries so frontend can rely on
                            # consistent top-level fields: `distance` and `phone`.
                            procs = []
                            for pp in raw["providers"]:
                                # Ensure phone exists as a top-level string
                                ph = (pp.get("phone") or "")
                                if isinstance(ph, dict):
                                    ph = ph.get("value", "")
                                pp["phone"] = (ph or "").strip()

                                # Ensure distance string exists (e.g. "4.5 mi").
                                if not pp.get("distance"):
                                    dm = pp.get("distance_miles")
                                    pp["distance"] = f"{round(dm,1)} mi" if (dm is not None) else ""

                                procs.append(pp)
                            state["providers"] = procs
                        audit_logger.log_event("PROVIDER_SEARCH", user_id, {
                            "count":     raw.get("count", 0),
                            "specialty": raw.get("specialty", ""),
                        })

                    elif fr.name == "check_availability":
                        state["availability"] = raw

                    elif fr.name == "book_appointment":
                        if raw.get("status") == "confirmed":
                            state["booking"] = raw

                    elif fr.name == "request_plan_change":
                        state.setdefault("_tool_results", []).append({"tool": fr.name, "output": raw})

                    # ── Rich reasoning: WHAT did the agent learn/decide? ─────────
                    decision = _build_tool_decision(fr.name, raw)

                    yield {"type": "tool_result", "tool": fr.name, "output": raw, "decision": decision}

            if event.is_final_response():
                final_text = ""
                if event.content and event.content.parts:
                    final_text = "".join(
                        p.text for p in event.content.parts if hasattr(p, "text") and p.text
                    )
                if not final_text.strip() and state["partial_texts"]:
                    final_text = "".join(state["partial_texts"])

                # ── Strip duplicate reasoning sentences and time slots from final text ─────────────────────────────
                import re as _re
                
                # Split into sentences to detect and remove exact duplicates (stuttering fix)
                _sentences = _re.split(r'(?<=[.!?])\s+', final_text)
                _unique_sentences = []
                _seen_sent = set()
                for _s in _sentences:
                    _clean_s = _s.strip().lower()
                    # Filter out redundant system-style skipped notes
                    if any(kw in _clean_s for kw in ["no slots available today", "no openings today", "showing next available"]):
                        continue
                    if _clean_s not in _seen_sent:
                        _unique_sentences.append(_s)
                        _seen_sent.add(_clean_s)
                final_text = " ".join(_unique_sentences)

                # Remove lines that are purely a time slot (e.g. "• 2:30 PM PST" or "- 3:00 PM")
                final_text = _re.sub(
                    r'(?m)^[\s\u2022\-\*]*\d{1,2}:\d{2}\s*(?:AM|PM)\s*(?:PST|CST|EST|MST|CDT|PDT|EDT)?\s*$',
                    '', final_text
                )
                # Remove inline slot enumerations like "at 2:00 PM, 2:30 PM, and 3:30 PM"
                final_text = _re.sub(
                    r'(?:at\s+)?(?:\d{1,2}:\d{2}\s*(?:AM|PM)\s*(?:PST|CST|EST|MST|CDT|PDT|EDT)?(?:\s*,\s*|\s+and\s+)){2,}\d{1,2}:\d{2}\s*(?:AM|PM)\s*(?:PST|CST|EST|MST|CDT|PDT|EDT)?',
                    '', final_text
                )
                # Remove "Which of these times works best?" type CTAs since card handles booking
                final_text = _re.sub(
                    r'(?i)which\s+(?:of\s+(?:these|those)\s+)?times?\s+works?\s+best.*?[?.]',
                    '', final_text
                )
                final_text = _re.sub(r'\n{3,}', '\n\n', final_text).strip()

                # ── Parse Pro Tip Guide if present ──
                pro_tip_guide = []
                if "PRO_TIP_GUIDE:" in final_text:
                    parts = final_text.split("PRO_TIP_GUIDE:")
                    final_text = parts[0].strip()
                    pro_tip_raw = parts[1].strip()
                    pro_tip_guide = [t.strip() for t in pro_tip_raw.split("|") if t.strip()]

                    # Append the "meanwhile" sentence if we successfully generated pro tips
                    if pro_tip_guide:
                        final_text += "\n\nMeanwhile, I’ve sent you some Pro Tips below — go ahead and tap the button to get helpful guidance until your visit."

                # ── Prepend reasoning sentence if agent acted on providers but gave no narrative ──
                # Only fires when the final text jumps straight to a doctor name or slot time
                # without any reasoning sentence.
                if state["providers"] and state.get("_tool_calls"):
                    _fp_call = next((e for e in state["_tool_calls"] if e["tool"] == "find_providers"), None)
                    if _fp_call:
                        _specialty = _fp_call["input"].get("specialty", "")
                        _urgency   = _fp_call["input"].get("urgency", "routine")
                        _fp_result = next((e for e in state.get("_tool_results", []) if e.get("tool") == "find_providers"), {})
                        _is_travel = bool(_fp_result.get("is_travel_search", False))
                        _oon = not state["providers"][0].get("in_network", True)

                        # Detect if the LLM has already provided reasoning to avoid "stuttering" repetition
                        _lower_text = final_text.strip().lower()
                        _already_has_reasoning = any(
                            _lower_text.startswith(w) for w in [
                                "since", "because", "as you", "i've searched", "that points", 
                                "your symptoms", "based on", "that sounds", "i have searched"
                            ]
                        )

                        _needs_prefix = final_text and not _already_has_reasoning and (
                            final_text.strip().startswith("Dr.") or
                            final_text.strip()[0].isdigit() or
                            final_text.strip().lower().startswith("here are") or
                            final_text.strip().lower().startswith("i found")
                        )
                        
                        try:
                            _user_r = _users.get_user(user_id)
                            _fname_r = _user_r.first_name
                            _oop_max_r = _get_plan_rules(_user_r.insurance_plan).get("oop_max", "$3,400")
                        except Exception:
                            _fname_r = ""
                            _oop_max_r = "$3,400"

                        # ── Build the empathetic financial message based on scenario ──
                        _fin_msg = ""
                        if _oon:
                            try:
                                _max_val = float(_oop_max_r.replace('$', '').replace(',', '').replace('/year', ''))
                                _est_cost = 150.0
                                _rem_val = _max_val - _est_cost
                                _rem_str = f"${_rem_val:,.0f}"
                                _max_str = f"${_max_val:,.0f}"
                            except Exception:
                                _rem_str = "unknown"
                                _max_str = _oop_max_r

                            _fin_msg = (
                                f"I completely understand you need to get this looked at, {_fname_r}. To help you plan ahead: "
                                f"since these options are out-of-network, a typical consultation will cost around **$150** out-of-pocket. "
                                f"This will count toward your **{_max_str}** annual out-of-pocket maximum, and your remaining maximum will be reduced to **{_rem_str}**. "
                            )
                        else:
                            _plan_rules_r = _get_plan_rules(_user_r.insurance_plan)
                            _spec_copay_r = _plan_rules_r.get("specialist_copay", "$0")
                            _pcp_copay_r = _plan_rules_r.get("pcp_copay", "$0")
                            
                            try:
                                _max_val = float(_oop_max_r.replace('$', '').replace(',', '').replace('/year', ''))
                                _max_str = f"${_max_val:,.0f}"
                                
                                if _specialty.lower() in ("primary care", "family medicine", "internal medicine"):
                                    _cost_val = float(_pcp_copay_r.replace('$', '').replace(',', ''))
                                    _copay_str = _pcp_copay_r
                                else:
                                    _cost_val = float(_spec_copay_r.replace('$', '').replace(',', ''))
                                    _copay_str = _spec_copay_r
                                    
                                _rem_val = _max_val - _cost_val
                                _rem_str = f"${_rem_val:,.0f}"
                            except Exception:
                                _rem_str = "unknown"
                                _max_str = _oop_max_r
                                _cost_val = 0
                                _copay_str = "$0"

                            if _cost_val == 0:
                                _fin_msg = (
                                    f"I've got some great news to help put your mind at ease, {_fname_r}. "
                                    f"Your plan has a **$0 copay** for this PCP consultation, so this visit will cost you absolutely nothing out-of-pocket. "
                                    f"Your annual out-of-pocket maximum remains untouched at **{_max_str}**. "
                                )
                            else:
                                _fin_msg = (
                                    f"I want to make sure you have all the details and are fully prepared for your visit, {_fname_r}. "
                                    f"Your plan requires a **{_copay_str} copay** for this in-network consultation. "
                                    f"This will count directly toward your **{_max_str}** annual out-of-pocket maximum, "
                                    f"meaning your remaining maximum will be reduced to **{_rem_str}**. "
                                )

                        if _needs_prefix and _specialty:
                            if _urgency == "urgent":
                                _prefix = f"That sounds urgent, {_fname_r} — I've prioritised the fastest available {_specialty.lower()} options near you. "
                            elif _is_travel:
                                _prefix = f"Since you're away from home, I've searched for {_specialty.lower()} doctors near your current location. "
                            else:
                                _prefix = _fin_msg

                            final_text = _prefix + final_text

                        # Ensure OOP/Cost Message is always included (Injector + Fallback Append)
                        if _fin_msg and _fin_msg.strip():
                            # Strip any existing half-baked or redundant financial sentences generated by the LLM
                            # to avoid double/triple explanations in final_text.
                            _text_sentences = _re.split(r'(?<=[.!?])\s+', final_text)
                            _clean_sentences = []
                            for _s in _text_sentences:
                                _s_lower = _s.lower()
                                if any(_kw in _s_lower for _kw in ["copay", "out-of-pocket", "out-of-network", "deductible"]):
                                    # Skip adding LLM-generated financial sentence because _fin_msg provides the perfect replacement
                                    continue
                                _clean_sentences.append(_s)
                            final_text = " ".join(_clean_sentences)

                            if _fin_msg.strip() not in final_text:
                                _inj_patterns = ["your assigned pcp", "dr. ", "i've found", "i've picked", "i found", "here is", "here are"]
                                _text_sentences = _re.split(r'(?<=[.!?])\s+', final_text)
                                _matched_idx = -1
                                for _idx, _s in enumerate(_text_sentences):
                                    if any(pat in _s.lower() for pat in _inj_patterns):
                                        _matched_idx = _idx
                                        break
                                
                                if _matched_idx != -1:
                                    _text_sentences.insert(_matched_idx, _fin_msg.strip())
                                    final_text = " ".join(_text_sentences)
                                else:
                                    # Fail-safe: append OOP/Cost message to the end of the narrative, before the Pro Tips button CTA if present
                                    _meanwhile_phrase = "Meanwhile, tap the Pro Tips button below"
                                    if _meanwhile_phrase in final_text:
                                        _parts = final_text.split(_meanwhile_phrase)
                                        final_text = _parts[0].rstrip() + " " + _fin_msg.strip() + "\n\n" + _meanwhile_phrase + _parts[1]
                                    else:
                                        final_text = final_text.rstrip() + " " + _fin_msg.strip()

                        # ── Paragraph Splitting Post-Processor ──
                        # Split final_text into 2 clean paragraphs: 
                        # Paragraph 1: Empathy + Clinical reasoning + Financial message
                        # Paragraph 2: Doctor recommendations / Booking CTA
                        _all_sentences = _re.split(r'(?<=[.!?])\s+', final_text)
                        _split_patterns = ["your assigned pcp", "dr. ", "i've found", "i've picked", "i found", "here is", "here are"]
                        _split_idx = -1
                        for _idx, _s in enumerate(_all_sentences):
                            if any(pat in _s.lower() for pat in _split_patterns):
                                if _idx >= 2:
                                    _split_idx = _idx
                                    break
                        
                        if _split_idx != -1:
                            _para1 = " ".join(_all_sentences[:_split_idx]).strip()
                            _para2 = " ".join(_all_sentences[_split_idx:]).strip()
                            final_text = f"{_para1}\n\n{_para2}"

                # ── Expand fallback to other tools ──────────────────────────────
                # Add reasoning prefixes for notify_provider, check_availability, book_appointment
                if not final_text.strip() or len(final_text.strip()) < 20:
                    # LLM returned empty or very short response — build one from tool results
                    _tool_calls = state.get("_tool_calls", [])
                    if _tool_calls:
                        _last_tool = _tool_calls[-1]["tool"]
                        if _last_tool == "notify_provider":
                            _provider = _tool_calls[-1]["input"].get("provider_name", "the provider")
                            _notif_type = _tool_calls[-1]["input"].get("notification_type", "")
                            if _notif_type == "prior_auth_request":
                                final_text = f"I've just notified {_provider}'s office to submit the prior auth to Cigna. These usually clear in 2-5 business days."
                            elif _notif_type == "referral_request":
                                final_text = f"I've sent a referral request to {_provider}'s office on your behalf."
                            else:
                                final_text = f"I've notified {_provider}'s office."
                        elif _last_tool == "check_availability" and state.get("availability"):
                            _avail = state["availability"]
                            _prov = _avail.get("provider_name", "the provider")
                            _date = _avail.get("date", "")
                            _slots = _avail.get("available_slots", [])
                            if _slots:
                                _slot_str = ", ".join(s.get("time_display", "") for s in _slots[:3])
                                final_text = f"{_prov} has availability on {_date}: {_slot_str}. Which time works for you?"
                        elif _last_tool == "book_appointment" and state.get("booking"):
                            _booking = state["booking"]
                            _prov = _booking.get("provider_name", "the provider")
                            _date = _booking.get("date", "")
                            _time = _booking.get("time_start", "")
                            _ctype = _booking.get("consultation_type", "")
                            _tele_link = _booking.get("telehealth_link", "")
                            if _ctype == "Telehealth":
                                final_text = (
                                    f"Done! I've switched your **{_date}** appointment with **{_prov}** "
                                    f"to a telehealth video call at **{_time}**. "
                                    f"You'll receive a link before the appointment."
                                )
                            else:
                                final_text = f"Done! Your appointment with {_prov} is confirmed for {_date} at {_time}."
                        elif _last_tool == "request_plan_change":
                            _pc_result = next(
                                (e for e in reversed(state.get("_tool_results", []))
                                 if e.get("tool") == "request_plan_change"),
                                None
                            )
                            if _pc_result and _pc_result.get("output", {}).get("status") == "submitted":
                                _new_plan = _pc_result.get("output", {}).get("new_plan", "your new plan")
                                try:
                                    _u = _users.get_user(user_id)
                                    _fn = _u.first_name
                                except Exception:
                                    _fn = ""
                                final_text = (
                                    f"Done, {_fn}! I've submitted your request to switch to **{_new_plan}** to Cigna for approval. "
                                    f"A representative will review it — once approved, your new plan takes effect immediately "
                                    f"and I'll let you know the moment you log back in. "
                                    f"Keep in mind that doctors in-network under your current plan may need to be re-verified under the new plan."
                                )

                # ── Validation guard: detect potential hallucinated confirmations ──
                if (
                    state["booking"] is None
                    and state.get("providers")
                    and "confirmed" in final_text.lower()
                ):
                    try:
                        audit_logger.log_event(
                            "POSSIBLE_HALLUCINATION",
                            user_id,
                            {"snippet": final_text[:200], "providers_count": len(state["providers"])},
                        )
                    except Exception:
                        pass

                if state["emergency"]:
                    result = {"type": "emergency", "message": final_text, "providers": []}

                elif state["booking"]:
                    # Safety net: if final_text is still empty, build confirmation from booking data
                    if not final_text.strip():
                        _bk = state["booking"]
                        _bk_prov = _bk.get("provider_name", "the provider")
                        _bk_date = _bk.get("date", "")
                        _bk_time = _bk.get("time_start", "")
                        _bk_type = _bk.get("consultation_type", "")
                        if _bk_type == "Telehealth":
                            final_text = (
                                f"Done! I've switched your **{_bk_date}** appointment with **{_bk_prov}** "
                                f"to a telehealth video call at **{_bk_time}**. "
                                f"You'll receive a link before the appointment. "
                                f"Meanwhile, tap the Pro Tips button below for some guidance until your visit."
                            )
                        else:
                            final_text = (
                                f"Done! Your appointment with {_bk_prov} is confirmed for {_bk_date} at {_bk_time}. "
                                f"Meanwhile, tap the Pro Tips button below for some guidance until you see the doctor."
                            )
                    result = {
                        "type":    "booking_confirmation",
                        "booking": state["booking"],
                        "message": final_text,
                        "pro_tip_guide": pro_tip_guide,
                    }

                elif state["providers"]:
                    # If both providers and availability are present (common in fresh search),
                    # prioritize provider_results so the structured provider objects (with _agentDate)
                    # are used by the frontend instead of parsing from text.
                    
                    # ── Sync agent-selected date from availability check ──────────
                    if state.get("availability"):
                        _avail_date = state["availability"].get("date_iso")
                        _avail_npi  = state["availability"].get("npi")
                        if _avail_date and _avail_npi:
                            for p in state["providers"]:
                                if str(p.get("npi")) == str(_avail_npi):
                                    p["_agentDate"] = _avail_date

                    _called_find_providers_this_turn = any(
                        c["tool"] == "find_providers" for c in state.get("_tool_calls", [])
                    )
                    if _called_find_providers_this_turn:
                        top = next(
                            (p for p in state["providers"] if p.get("top_pick")),
                            state["providers"][0]
                        )
                        result = {
                            "type":      "provider_results",
                            "providers": state["providers"],
                            "top_pick":  top,
                            "message":   final_text,
                        }
                    else:
                        result = {"type": "chat", "explanation": final_text}

                elif state["availability"]:
                    result = {
                        "type":         "availability",
                        "availability": state["availability"],
                        "message":      final_text,
                    }

                else:
                    result = {"type": "chat", "explanation": final_text}

                if message not in ("__plan_change_greeting__", "__location_change__", "__session_start__"):
                    storage.save_turn(user_id, "user", message)
                if final_text.strip():
                    storage.save_turn(user_id, "assistant", final_text)

                yield {"type": "final", "response": result}

    except asyncio.TimeoutError:
        yield {"type": "error", "message": "Request timed out — Vertex AI unreachable or GCP credentials expired. Run: gcloud auth application-default login"}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        yield {"type": "error", "message": str(exc)}
