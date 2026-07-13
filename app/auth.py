import os
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from sqlalchemy import text

SESSION_COOKIE = "revisit_session"
SESSION_TTL_SECONDS = 7 * 24 * 3600


class UnauthenticatedUI(Exception):
    """Raised by UI route dependencies to trigger a redirect to /login."""


def auth_enabled() -> bool:
    return os.environ.get("AUTH_ENABLED", "false").lower() == "true"


def _db():
    from app.db import SessionLocal
    return SessionLocal()


def create_session() -> str:
    token = secrets.token_hex(32)
    expires_at = int(datetime.now(timezone.utc).timestamp()) + SESSION_TTL_SECONDS
    db = _db()
    try:
        db.execute(
            text("INSERT INTO sessions (token, expires_at) VALUES (:token, :expires_at)"),
            {"token": token, "expires_at": expires_at},
        )
        db.commit()
    finally:
        db.close()
    return token


def revoke_session(token: str) -> None:
    if not token:
        return
    db = _db()
    try:
        db.execute(text("DELETE FROM sessions WHERE token = :token"), {"token": token})
        db.commit()
    finally:
        db.close()


def _is_valid(token: str | None) -> bool:
    if not token:
        return False
    now = int(datetime.now(timezone.utc).timestamp())
    db = _db()
    try:
        row = db.execute(
            text("SELECT 1 FROM sessions WHERE token = :token AND expires_at > :now"),
            {"token": token, "now": now},
        ).fetchone()
        return row is not None
    finally:
        db.close()


def check_credentials(username: str, password: str) -> bool:
    expected_user = os.environ.get("APP_USERNAME", "")
    expected_pass = os.environ.get("APP_PASSWORD", "")
    return bool(expected_user) and username == expected_user and password == expected_pass


def require_auth(request: Request) -> None:
    """FastAPI dependency for API routes: returns 401 when auth is on and session is invalid."""
    if not auth_enabled():
        return
    if not _is_valid(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_ui_auth(request: Request) -> None:
    """FastAPI dependency for UI routes: raises UnauthenticatedUI to trigger a /login redirect."""
    if not auth_enabled():
        return
    if not _is_valid(request.cookies.get(SESSION_COOKIE)):
        raise UnauthenticatedUI()
