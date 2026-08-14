from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import auth_enabled, require_operator, require_ui_auth

router = APIRouter(prefix="/app", tags=["ui"])
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


def _ctx(request: Request) -> dict:
    return {"auth_enabled": auth_enabled()}


@router.get("/", response_class=RedirectResponse)
def ui_root() -> RedirectResponse:
    return RedirectResponse(url="/app/capture")


@router.get("/capture", response_class=HTMLResponse)
def capture_page(request: Request, _: None = Depends(require_ui_auth)) -> HTMLResponse:
    return templates.TemplateResponse(request, "capture.html", _ctx(request))


@router.get("/backlog", response_class=HTMLResponse)
def backlog_page(request: Request, _: None = Depends(require_ui_auth)) -> HTMLResponse:
    return templates.TemplateResponse(request, "backlog.html", _ctx(request))


@router.get("/clusters", response_class=HTMLResponse)
def clusters_page(request: Request, _: None = Depends(require_ui_auth)) -> HTMLResponse:
    return templates.TemplateResponse(request, "clusters.html", _ctx(request))


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, _: None = Depends(require_ui_auth)) -> HTMLResponse:
    return templates.TemplateResponse(request, "jobs.html", _ctx(request))


@router.get("/metrics", response_class=HTMLResponse)
def metrics_page(request: Request, _: None = Depends(require_ui_auth)) -> HTMLResponse:
    return templates.TemplateResponse(request, "metrics.html", _ctx(request))


@router.get("/telemetry", response_class=HTMLResponse)
def telemetry_page(request: Request, _=Depends(require_operator)) -> HTMLResponse:
    return templates.TemplateResponse(request, "telemetry.html", _ctx(request))


@router.get("/memory", response_class=HTMLResponse)
def memory_page(request: Request, _: None = Depends(require_ui_auth)) -> HTMLResponse:
    return templates.TemplateResponse(request, "memory.html", _ctx(request))
