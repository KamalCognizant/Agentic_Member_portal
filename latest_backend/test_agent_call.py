import asyncio
import os
import json

# Ensure local SSL patching in test runs

# Load environment variables from the repo .env (so local changes propagate)
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

os.environ.setdefault("APP_ENV", "local")

# Apply the same local SSL no-verify patch used by `run.py` so tests
# can call the Google GenAI endpoints from a dev box with intercepting
# proxies or missing cert bundles.
import ssl, warnings
if os.getenv("APP_ENV", "local") == "local":
    _orig_create_default_context = ssl.create_default_context

    def _patched_create_default_context(purpose=ssl.Purpose.SERVER_AUTH, *a, **kw):
        ctx = _orig_create_default_context(purpose, *a, **kw)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    ssl.create_default_context = _patched_create_default_context
    warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

# Run a single ad-hoc invocation of run_adk_agent_stream
from app.adk.agent import run_adk_agent_stream

async def main():
    print('Starting ad-hoc agent test')
    try:
        async for event in run_adk_agent_stream("I need a new primary care doctor in Seattle", "test_user"):
            print(json.dumps(event, ensure_ascii=False))
    except Exception as e:
        import traceback
        traceback.print_exc()
        print('ERROR:', e)


if __name__ == '__main__':
    asyncio.run(main())
