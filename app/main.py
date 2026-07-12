import logging

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

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
from app.auth import UnauthenticatedUI

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Revisit Capture API")


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


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/app/capture")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
