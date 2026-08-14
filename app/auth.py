import os
import secrets
import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import select, text

from app.models.user import ExtensionTokenORM, UserORM

SESSION_COOKIE = "revisit_session"
SESSION_TTL_SECONDS = 7 * 24 * 3600


class UnauthenticatedUI(Exception):
    """Raised by UI route dependencies to trigger a redirect to /login."""


def auth_enabled() -> bool:
    return os.environ.get("AUTH_ENABLED", "false").lower() == "true"


def require_legacy_pipeline_disabled_in_production() -> None:
    """Keep experimental clustering/card endpoints unreachable in production."""
    if os.environ.get("ENVIRONMENT") == "production":
        raise HTTPException(status_code=404, detail="Not found")


def _db():
    from app.db import SessionLocal
    return SessionLocal()


def create_session(user_id: str | None = None) -> str:
    token = secrets.token_hex(32)
    expires_at = int(datetime.now(timezone.utc).timestamp()) + SESSION_TTL_SECONDS
    db = _db()
    try:
        db.execute(
            text("INSERT INTO sessions (token, expires_at, user_id, csrf_token) VALUES (:token, :expires_at, :user_id, :csrf)"),
            {"token": token, "expires_at": expires_at, "user_id": user_id, "csrf": secrets.token_urlsafe(24)},
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


def _session_user(token: str | None) -> UserORM | None:
    if not token:
        return None
    now = int(datetime.now(timezone.utc).timestamp())
    db = _db()
    try:
        row = db.execute(text(
            "SELECT users.id FROM sessions JOIN users ON users.id=sessions.user_id "
            "WHERE sessions.token=:token AND sessions.expires_at>:now"
        ), {"token": token, "now": now}).fetchone()
        user = db.get(UserORM, row[0]) if row else None
        if user:
            db.expunge(user)
        return user
    finally:
        db.close()


def require_auth(request: Request) -> UserORM | None:
    """FastAPI dependency for API routes: returns 401 when auth is on and session is invalid."""
    if not auth_enabled():
        return None
    if not _is_valid(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return _session_user(request.cookies.get(SESSION_COOKIE))


def require_ui_auth(request: Request) -> None:
    """FastAPI dependency for UI routes: raises UnauthenticatedUI to trigger a /login redirect."""
    if not auth_enabled():
        return
    if not _is_valid(request.cookies.get(SESSION_COOKIE)):
        raise UnauthenticatedUI()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def upsert_google_user(profile: dict) -> UserORM:
    google_sub = str(profile.get("sub") or profile.get("id") or "")
    email = str(profile.get("email") or "").lower()
    if not google_sub or not email or profile.get("email_verified") is False:
        raise HTTPException(status_code=401, detail="Google account is not verified")
    db = _db()
    try:
        user = db.scalar(select(UserORM).where(UserORM.google_sub == google_sub))
        if user is None:
            user = UserORM(
                id=str(uuid.uuid4()), google_sub=google_sub, email=email,
                display_name=profile.get("name"), avatar_url=profile.get("picture"),
            )
            db.add(user)
        else:
            user.email = email
            user.display_name = profile.get("name") or user.display_name
            user.avatar_url = profile.get("picture") or user.avatar_url
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user
    finally:
        db.close()


def issue_extension_token(user_id: str) -> tuple[str, int]:
    raw = secrets.token_urlsafe(48)
    expires_at = int(datetime.now(timezone.utc).timestamp()) + 90 * 24 * 3600
    db = _db()
    try:
        db.add(ExtensionTokenORM(
            id=str(uuid.uuid4()), user_id=user_id, token_hash=token_hash(raw), expires_at=expires_at
        ))
        db.commit()
    finally:
        db.close()
    return raw, expires_at


def current_user(request: Request) -> UserORM:
    """Authenticate a public API request with a revocable bearer token or web session."""
    db = _db()
    try:
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            raw = authorization.split(" ", 1)[1]
            now = int(datetime.now(timezone.utc).timestamp())
            credential = db.scalar(
                select(ExtensionTokenORM).where(
                    ExtensionTokenORM.token_hash == token_hash(raw),
                    ExtensionTokenORM.revoked_at.is_(None),
                    ExtensionTokenORM.expires_at > now,
                )
            )
            user = db.get(UserORM, credential.user_id) if credential else None
        else:
            token = request.cookies.get(SESSION_COOKIE)
            now = int(datetime.now(timezone.utc).timestamp())
            row = db.execute(
                text("SELECT user_id FROM sessions WHERE token=:token AND expires_at>:now"),
                {"token": token, "now": now},
            ).fetchone() if token else None
            user = db.get(UserORM, row[0]) if row and row[0] else None
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        db.expunge(user)
        return user
    finally:
        db.close()


def require_operator(request: Request) -> UserORM | None:
    """Allow configured beta operators without exposing admin-route existence."""
    if os.environ.get("ENVIRONMENT") != "production" and not auth_enabled():
        return None
    user = current_user(request)
    allowed = {email.strip().lower() for email in os.environ.get("ADMIN_EMAILS", "").split(",") if email.strip()}
    if user.email.lower() not in allowed:
        raise HTTPException(status_code=404, detail="Not found")
    return user
