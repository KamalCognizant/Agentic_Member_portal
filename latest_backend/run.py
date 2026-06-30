"""
Start the server without --reload to avoid Python 3.14 multiprocessing/logging crash.
Usage: python run.py
"""
# ── SSL patch — MUST be first, before any httpx / google-genai import ─────────
import os, ssl, warnings

if os.getenv("APP_ENV", "local") == "local":
    import httpx

    _orig_create_default_context = ssl.create_default_context

    def _patched_create_default_context(purpose=ssl.Purpose.SERVER_AUTH, *a, **kw):
        ctx = _orig_create_default_context(purpose, *a, **kw)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    ssl.create_default_context = _patched_create_default_context

    _OrigAsync = httpx.AsyncClient
    _OrigSync  = httpx.Client

    class _NoVerifyAsync(_OrigAsync):
        def __init__(self, *a, **kw):
            kw["verify"] = False
            super().__init__(*a, **kw)

    class _NoVerifySync(_OrigSync):
        def __init__(self, *a, **kw):
            kw["verify"] = False
            super().__init__(*a, **kw)

    httpx.AsyncClient = _NoVerifyAsync
    httpx.Client      = _NoVerifySync

    warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
# ──────────────────────────────────────────────────────────────────────────────

import uvicorn

uvicorn.run(
    "app.main:app",
    host="0.0.0.0",
    port=int(os.getenv("PORT", 8080)),
    reload=False,
)