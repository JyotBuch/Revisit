import logging
import os
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text

from app.api.captures import router as captures_router
from app.api.clusters import router as clusters_router
from app.api.feedback import router as feedback_router
from app.api.jobs import router as jobs_router
from app.api.login import router as login_router
from app.api.metrics import router as metrics_router
from app.api.resources import router as resources_router
from app.api.revisit_cards import router as revisit_cards_router
from app.api.telemetry import router as telemetry_router
from app.api.ui import router as ui_router
from app.api.v1 import router as v1_router
from app.auth import UnauthenticatedUI
from app.db import engine

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Revisit Capture API")

if os.environ.get("ENVIRONMENT") == "production":
    required = ["DATABASE_URL", "GOOGLE_WEB_CLIENT_ID", "GOOGLE_WEB_CLIENT_SECRET", "GOOGLE_WEB_REDIRECT_URI", "GOOGLE_EXTENSION_CLIENT_ID", "ALLOWED_EXTENSION_ORIGINS"]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError(f"Missing production configuration: {', '.join(missing)}")

allowed_origins = [origin.strip() for origin in os.environ.get("ALLOWED_EXTENSION_ORIGINS", "").split(",") if origin.strip()]
if allowed_origins:
    app.add_middleware(
        CORSMiddleware, allow_origins=allowed_origins, allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
allowed_hosts = [host.strip() for host in os.environ.get("ALLOWED_HOSTS", "*").split(",") if host.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

_request_windows: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def public_api_rate_limit(request: Request, call_next):
    if (
        request.method in {"POST", "PATCH", "PUT", "DELETE"}
        and request.cookies.get("revisit_session")
        and not request.headers.get("authorization", "").lower().startswith("bearer ")
    ):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.url.netloc:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Cross-site request rejected"}, status_code=403)
    if request.url.path.startswith("/api/v1"):
        if (
            request.method in {"POST", "PATCH", "PUT", "DELETE"}
            and request.cookies.get("revisit_session")
            and not request.headers.get("authorization", "").lower().startswith("bearer ")
        ):
            origin = request.headers.get("origin")
            if not origin or urlparse(origin).netloc != request.url.netloc:
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Cross-site request rejected"}, status_code=403)
        key = request.headers.get("authorization") or (request.client.host if request.client else "unknown")
        now = time.monotonic()
        window = _request_windows[key]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= int(os.environ.get("API_RATE_LIMIT_PER_MINUTE", "120")):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
        window.append(now)
    return await call_next(request)


@app.exception_handler(UnauthenticatedUI)
async def unauthenticated_ui_handler(request: Request, exc: UnauthenticatedUI) -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=302)


app.include_router(login_router)
app.include_router(captures_router)
app.include_router(revisit_cards_router)
app.include_router(clusters_router)
app.include_router(feedback_router)
app.include_router(metrics_router)
app.include_router(jobs_router)
app.include_router(resources_router)
app.include_router(telemetry_router)
app.include_router(ui_router)
app.include_router(v1_router)


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/app/capture")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ready"}
