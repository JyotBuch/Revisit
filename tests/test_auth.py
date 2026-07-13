"""Integration tests for authentication.

auth disabled (default in CI/dev): all existing behaviour is preserved.
auth enabled (AUTH_ENABLED=true): UI pages redirect to /login, protected
POST API endpoints return 401, valid login grants access, logout revokes it.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import get_db
from tests.conftest import TestSessionLocal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def no_redirect_client() -> TestClient:
    """TestClient that does NOT follow redirects — needed to assert 302 locations."""
    def _override_get_db():
        session = TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clear_sessions():
    """Sessions are cleared by the conftest clean_db fixture (truncates sessions table)."""
    yield


# ---------------------------------------------------------------------------
# Auth disabled (default) — existing behaviour must be unchanged
# ---------------------------------------------------------------------------

def test_auth_disabled_ui_returns_200(no_redirect_client):
    assert no_redirect_client.get("/app/capture").status_code == 200


def test_auth_disabled_api_post_allowed(client):
    resp = client.post(
        "/captures",
        json={"source_type": "note", "user_note": "test", "label": "casual"},
    )
    assert resp.status_code == 201


def test_login_page_returns_200_regardless_of_auth(no_redirect_client):
    assert no_redirect_client.get("/login").status_code == 200


# ---------------------------------------------------------------------------
# Auth enabled — UI redirects
# ---------------------------------------------------------------------------

def test_auth_enabled_ui_redirects_to_login(monkeypatch, no_redirect_client):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    for path in ["/app/capture", "/app/backlog", "/app/clusters", "/app/jobs", "/app/metrics"]:
        resp = no_redirect_client.get(path)
        assert resp.status_code == 302, f"Expected 302 for {path}, got {resp.status_code}"
        assert resp.headers["location"] == "/login", f"Expected /login redirect for {path}"


def test_auth_enabled_root_redirect_is_not_blocked(monkeypatch, no_redirect_client):
    """/ → /app/capture is a plain redirect, not auth-guarded itself."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    resp = no_redirect_client.get("/")
    assert resp.status_code == 307


# ---------------------------------------------------------------------------
# Auth enabled — API mutation endpoints return 401
# ---------------------------------------------------------------------------

def test_auth_enabled_blocks_post_captures(monkeypatch, no_redirect_client):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    resp = no_redirect_client.post(
        "/captures",
        json={"source_type": "note", "user_note": "test", "label": "casual"},
    )
    assert resp.status_code == 401


def test_auth_enabled_blocks_post_jobs(monkeypatch, no_redirect_client):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    resp = no_redirect_client.post("/jobs/daily-batch")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Login endpoint
# ---------------------------------------------------------------------------

def test_login_valid_credentials_sets_cookie(monkeypatch, no_redirect_client):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    resp = no_redirect_client.post("/login", json={"username": "admin", "password": "secret"})
    assert resp.status_code == 200
    assert "revisit_session" in resp.cookies


def test_login_invalid_password_returns_401(monkeypatch, no_redirect_client):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    resp = no_redirect_client.post("/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


def test_login_invalid_username_returns_401(monkeypatch, no_redirect_client):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    resp = no_redirect_client.post("/login", json={"username": "hacker", "password": "secret"})
    assert resp.status_code == 401


def test_login_missing_fields_returns_422(no_redirect_client):
    resp = no_redirect_client.post("/login", json={"username": "admin"})
    assert resp.status_code == 422


def test_login_unconfigured_credentials_always_fails(monkeypatch, no_redirect_client):
    """When APP_USERNAME is not set, all logins must fail — prevents accidental open access."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)

    resp = no_redirect_client.post("/login", json={"username": "", "password": ""})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Session lifecycle: login → access → logout → blocked again
# ---------------------------------------------------------------------------

def test_logged_in_can_access_protected_ui(monkeypatch, no_redirect_client):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    no_redirect_client.post("/login", json={"username": "admin", "password": "secret"})
    resp = no_redirect_client.get("/app/capture")
    assert resp.status_code == 200


def test_logged_in_can_post_captures(monkeypatch, no_redirect_client):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    no_redirect_client.post("/login", json={"username": "admin", "password": "secret"})
    resp = no_redirect_client.post(
        "/captures",
        json={"source_type": "note", "user_note": "test", "label": "casual"},
    )
    assert resp.status_code == 201


def test_logout_blocks_subsequent_api_calls(monkeypatch, no_redirect_client):
    """After logout the session token is revoked; POST /captures must return 401."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    no_redirect_client.post("/login", json={"username": "admin", "password": "secret"})
    assert no_redirect_client.post(
        "/captures",
        json={"source_type": "note", "user_note": "pre-logout", "label": "casual"},
    ).status_code == 201

    no_redirect_client.post("/logout")

    resp = no_redirect_client.post(
        "/captures",
        json={"source_type": "note", "user_note": "post-logout", "label": "casual"},
    )
    assert resp.status_code == 401


def test_logout_clears_session(monkeypatch, no_redirect_client):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    no_redirect_client.post("/login", json={"username": "admin", "password": "secret"})
    assert no_redirect_client.get("/app/capture").status_code == 200

    no_redirect_client.post("/logout")

    resp = no_redirect_client.get("/app/capture")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"
