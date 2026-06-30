"""
Corporate proxy SSL patch for local dev.
Disables SSL certificate verification on all httpx clients created after this
module is imported — which includes the internal client used by google-genai SDK.

This is safe for local development behind a corporate TLS-intercepting proxy.
Do NOT use in production (set APP_ENV != 'local' to skip the patch).
"""
import os

_app_env = os.getenv("APP_ENV", "local")
if _app_env == "local":
    import ssl
    import httpx

    # 1. Disable SSL verification on all new ssl.SSLContext objects created via
    #    create_default_context so legacy libraries pick it up.
    _orig_create_default_context = ssl.create_default_context

    def _patched_create_default_context(purpose=ssl.Purpose.SERVER_AUTH, *args, **kwargs):
        ctx = _orig_create_default_context(purpose, *args, **kwargs)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    ssl.create_default_context = _patched_create_default_context

    # 2. Patch httpx.AsyncClient and httpx.Client so every instance created
    #    anywhere in the process (including inside google-genai) uses verify=False.
    _OrigAsyncClient = httpx.AsyncClient
    _OrigSyncClient = httpx.Client

    class _PatchedAsyncClient(_OrigAsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["verify"] = False
            super().__init__(*args, **kwargs)

    class _PatchedSyncClient(_OrigSyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["verify"] = False
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = _PatchedAsyncClient
    httpx.Client = _PatchedSyncClient

    # 3. Suppress the InsecureRequestWarning that urllib3/httpx would otherwise log.
    import warnings
    warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
