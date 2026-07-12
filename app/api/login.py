from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import auth

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html")


@router.post("/login")
def do_login(body: LoginRequest) -> JSONResponse:
    if not auth.check_credentials(body.username, body.password):
        return JSONResponse(status_code=401, content={"detail": "Invalid credentials"})
    token = auth.create_session()
    resp = JSONResponse(status_code=200, content={"ok": True})
    resp.set_cookie(
        key=auth.SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return resp


@router.post("/logout")
def do_logout(request: Request) -> JSONResponse:
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        auth.revoke_session(token)
    resp = JSONResponse(status_code=200, content={"ok": True})
    resp.delete_cookie(key=auth.SESSION_COOKIE)
    return resp
