import os
import secrets

from fastapi import HTTPException, Request

SESSION_COOKIE = "revisit_session"
_active_sessions: set[str] = set()


class UnauthenticatedUI(Exception):
    """Raised by UI route dependencies to trigger a redirect to /login."""


def auth_enabled() -> bool:
    return os.environ.get("AUTH_ENABLED", "false").lower() == "true"


def create_session() -> str:
    token = secrets.token_hex(32)
    _active_sessions.add(token)
    return token


def revoke_session(token: str) -> None:
    _active_sessions.discard(token)


def _is_valid(token: str | None) -> bool:
    return bool(token and token in _active_sessions)


def check_credentials(username: str, password: str) -> bool:
    expected_user = os.environ.get("APP_USERNAME", "")
    expected_pass = os.environ.get("APP_PASSWORD", "")
    # Reject if APP_USERNAME is not configured — an empty username would match anything.
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
