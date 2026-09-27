import logging
import os
import secrets
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

# Load .env from the same directory as main.py. This MUST happen before the
# router imports below: routers/rag.py snapshots LLM API keys into module
# globals at import time, so loading afterwards leaves it with no provider.
load_dotenv(Path(__file__).parent / ".env")

from routers.fetch import router as fetch_router  # noqa: E402
from routers.models import router as models_router  # noqa: E402
from routers.portfolio import router as portfolio_router  # noqa: E402
from routers.rag import router as rag_router  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("alphastratum")

# The backend is deployed to a public hostname, so every route is treated as
# private unless it is on this list. Keep it as small as possible: the Render
# health check is the only caller that legitimately has no credential.
PUBLIC_PATHS = {"/health"}

# Values that appear in .env.example / README. Shipping the example file to a
# real host would otherwise "protect" the API with a string that is public in
# this repository, which is worse than no password because it looks configured.
_PLACEHOLDER_PASSWORDS = frozenset(
    {
        "change_me_to_a_strong_random_string",
        "your_secure_password_here",
        "changeme",
        "password",
    }
)

# Failed-auth throttle. A single shared secret on a public URL is otherwise
# brute-forceable without limit. Counted per peer address, per process; this is
# a speed bump, not a distributed rate limiter.
_AUTH_FAIL_LIMIT = int(os.getenv("AUTH_FAIL_LIMIT", "10"))
_AUTH_FAIL_WINDOW_S = float(os.getenv("AUTH_FAIL_WINDOW_S", "300"))
_MAX_TRACKED_CLIENTS = 10_000
_fail_counts: dict[str, list[float]] = {}
_fail_lock = threading.Lock()


def _auth_password() -> str:
    # Read per-request so tests (and runtime env changes) see the current value.
    return os.getenv("AUTH_PASSWORD", "").strip()


def _password_is_placeholder(password: str) -> bool:
    return password.lower() in _PLACEHOLDER_PASSWORDS


def _auth_configured() -> bool:
    password = _auth_password()
    return bool(password) and not _password_is_placeholder(password)


def _dev_mode() -> bool:
    """Explicit opt-in for running the API without any credential.

    This is now the ONLY way to get an unauthenticated API, and it is off by
    default, so a deploy that forgets AUTH_PASSWORD refuses traffic instead of
    publishing it.
    """
    return os.getenv("AUTH_DEV_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def _client_key(request: Request) -> str:
    """Identify the caller for throttling.

    Uses the peer address that uvicorn resolved, which is the real client only
    when the server runs with --proxy-headers --forwarded-allow-ips (set in
    render.yaml). The raw X-Forwarded-For header is deliberately not trusted
    here: it is attacker-controlled and would let anyone mint a fresh bucket
    per request by rotating the value.
    """
    return request.client.host if request.client else "unknown"


def _throttled(key: str) -> bool:
    now = time.monotonic()
    with _fail_lock:
        hits = [t for t in _fail_counts.get(key, []) if now - t < _AUTH_FAIL_WINDOW_S]
        if hits:
            _fail_counts[key] = hits
            return len(hits) >= _AUTH_FAIL_LIMIT
        _fail_counts.pop(key, None)
        return False


def _record_failure(key: str) -> None:
    now = time.monotonic()
    with _fail_lock:
        hits = [t for t in _fail_counts.get(key, []) if now - t < _AUTH_FAIL_WINDOW_S]
        hits.append(now)
        _fail_counts[key] = hits
        # Opportunistic bound so a spray of distinct source addresses cannot
        # grow this dict without limit. Runs AFTER the insert so the cap holds
        # on return. Mutate in place — rebinding the module global here would
        # shadow it for the rest of the function.
        if len(_fail_counts) > _MAX_TRACKED_CLIENTS:
            cutoff = now - _AUTH_FAIL_WINDOW_S
            for k in [k for k, v in _fail_counts.items() if not v or v[-1] < cutoff]:
                del _fail_counts[k]
            if len(_fail_counts) > _MAX_TRACKED_CLIENTS:
                # Still oversized (every entry is fresh): drop the oldest
                # surplus rather than let the table grow without limit.
                surplus = len(_fail_counts) - _MAX_TRACKED_CLIENTS
                for k in sorted(_fail_counts, key=lambda k: _fail_counts[k][-1])[:surplus]:
                    del _fail_counts[k]


def _reset_failures(key: str) -> None:
    with _fail_lock:
        _fail_counts.pop(key, None)


def _log_auth_posture() -> None:
    if _auth_configured():
        return
    if _auth_password() and _password_is_placeholder(_auth_password()):
        logger.error(
            "AUTH_PASSWORD is still the example placeholder — the API will reject "
            "all requests. Generate a real secret: openssl rand -base64 32"
        )
    elif _dev_mode():
        logger.warning(
            "AUTH_DEV_MODE=1 with no AUTH_PASSWORD — the API is UNAUTHENTICATED and "
            "reachable by anyone who finds this host. Never set this in production."
        )
    else:
        logger.error(
            "AUTH_PASSWORD is not set — the API will reject all requests. Set a "
            "strong random AUTH_PASSWORD, or AUTH_DEV_MODE=1 for local development."
        )


_log_auth_posture()

app = FastAPI(title="Alpha Stratum API", version="0.2.0")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    # Fail closed: an unset or placeholder secret means "no access", never
    # "allow all". Only an explicit AUTH_DEV_MODE=1 opens the door, and that
    # flag is documented as local-development-only.
    if not _auth_configured():
        if _dev_mode():
            return await call_next(request)
        return JSONResponse(
            status_code=503,
            content={"detail": "Authentication is not configured on this server"},
        )

    key = _client_key(request)
    if _throttled(key):
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many failed authentication attempts"},
            headers={"Retry-After": str(int(_AUTH_FAIL_WINDOW_S))},
        )

    # Prefer the X-Auth-Key header. A `?key=` query param still works (for
    # curl / docs), but it lands in every access log, proxy log and browser
    # history along with the shared secret, so the app's own proxy sends the
    # header instead.
    password = _auth_password()
    provided = request.headers.get("x-auth-key") or request.query_params.get("key", "")
    # compare_digest on encoded bytes avoids str-encoding TypeErrors and
    # short-circuit timing leaks.
    if not provided or not secrets.compare_digest(provided.encode(), password.encode()):
        _record_failure(key)
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    _reset_failures(key)
    return await call_next(request)


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["http://localhost:3000"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,  # auth is a shared-secret header, not cookies
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(fetch_router, prefix="/fetch", tags=["fetch"])
app.include_router(models_router, prefix="/models", tags=["models"])
app.include_router(rag_router, prefix="/rag", tags=["rag"])
app.include_router(portfolio_router, tags=["portfolio"])


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/")
def root():
    return {"status": "ok", "service": "Alpha Stratum API"}


@app.get("/health")
def health():
    from services.database import check_connection

    # Deliberately says nothing about auth. This endpoint is unauthenticated so
    # Render can poll it, which makes it the one place an anonymous caller can
    # read the response; reporting whether a credential is configured would
    # hand a scanner a free "is this host open?" oracle. Startup logs the
    # posture instead.
    return {"status": "healthy", "database": check_connection()}
