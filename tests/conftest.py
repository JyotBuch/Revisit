"""Shared fixtures for integration tests against revisit_test database.

Each test runs against a real PostgreSQL database (revisit_test) with all
migrations applied. Tables are truncated before every test for isolation.

Requirements:
  - revisit_test database must exist with pgvector enabled.
  - Run `make db-test-setup` once to create it (see Makefile).
  - Tests run with fake embeddings (no OPENAI_API_KEY required).
"""

import os

# Point at the test DB before importing app modules that read DATABASE_URL at
# module load time. Must happen before any app import.
os.environ["DATABASE_URL"] = "postgresql+psycopg2://revisit:revisit@localhost:5432/revisit_test"
# Disable real API calls; embeddings fall back to fake-local-dev-v1.
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("SEARCH_PROVIDER", None)
os.environ.pop("TAVILY_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("SEARCH_API_KEY", None)

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from fastapi.testclient import TestClient

from app.main import app
from app.db import get_db

TEST_DATABASE_URL = os.environ["DATABASE_URL"]
test_engine = create_engine(TEST_DATABASE_URL)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

# Ordered so that FK-dependent tables are cleared before their parents.
_TABLES_TO_TRUNCATE = [
    "newsletter_item_revisions",
    "newsletter_feedback",
    "newsletter_captures",
    "newsletters",
    "agent_memories",
    "telemetry_daily_aggregates",
    "idempotency_keys",
    "extension_tokens",
    "revisit_card_resources",
    "revisit_card_feedback",
    "revisit_cards",
    "resources",
    "cluster_items",
    "clusters",
    "capture_embeddings",
    "captures",
    "jobs",
    "llm_calls",
    "agent_steps",
    "retrieval_events",
    "sessions",
    "users",
]


def _truncate_all() -> None:
    with test_engine.connect() as conn:
        # Single TRUNCATE with CASCADE is faster and simpler than individual
        # statements, but we list tables explicitly to avoid touching anything
        # outside the scope of this project's schema.
        tables = ", ".join(_TABLES_TO_TRUNCATE)
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        conn.commit()


@pytest.fixture(autouse=True)
def clean_db() -> None:
    """Truncate all tables before each test so every test starts clean."""
    _truncate_all()
    yield


@pytest.fixture
def db() -> Session:
    """Direct DB session for test setup that needs to bypass the HTTP layer."""
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient wired to the test database."""
    def _override_get_db():
        session = TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
