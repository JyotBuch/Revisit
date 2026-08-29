"""Tests for OpenAI-backed related-resource retrieval."""

import uuid
from unittest.mock import MagicMock, patch

from app.models.capture import CaptureORM
from app.models.cluster import ClusterItemORM, ClusterORM
from app.services.retrieval import FAKE_PROVIDER_NAME, _get_api_key


def _cluster(db):
    cap = CaptureORM(id=str(uuid.uuid4()), source_type="article", label="return",
        status="extracted", url="https://example.com/ai", title="Introduction to AI",
        extracted_text="Artificial intelligence basics")
    db.add(cap); db.flush()
    cluster = ClusterORM(id=str(uuid.uuid4()), title="Artificial Intelligence", status="active")
    db.add(cluster); db.flush()
    db.add(ClusterItemORM(id=str(uuid.uuid4()), cluster_id=cluster.id, capture_id=cap.id))
    db.commit()
    return cluster


def test_get_api_key_openai_uses_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert _get_api_key("openai") == "sk-test"


def test_get_api_key_openai_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert _get_api_key("openai") is None


def test_get_api_key_brave_uses_search_api_key(monkeypatch):
    monkeypatch.setenv("SEARCH_API_KEY", "brave-key")
    assert _get_api_key("brave") == "brave-key"


def test_no_provider_configured_uses_fake(client, db):
    cluster = _cluster(db)
    from app.services.retrieval import retrieve_resources_for_cluster
    candidates = retrieve_resources_for_cluster(db, cluster.id, limit=3)
    assert len(candidates) == 3
    assert all(c.provider == FAKE_PROVIDER_NAME for c in candidates)


def test_openai_provider_no_key_falls_back_to_fake(monkeypatch, client, db):
    monkeypatch.setenv("SEARCH_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cluster = _cluster(db)
    from app.services.retrieval import retrieve_resources_for_cluster
    candidates = retrieve_resources_for_cluster(db, cluster.id, limit=2)
    assert all(c.provider == FAKE_PROVIDER_NAME for c in candidates)


def test_openai_provider_failure_falls_back_to_fake(monkeypatch, client, db):
    monkeypatch.setenv("SEARCH_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cluster = _cluster(db)
    from app.services.retrieval import retrieve_resources_for_cluster
    with patch("app.services.retrieval._openai_search", side_effect=Exception("timeout")):
        candidates = retrieve_resources_for_cluster(db, cluster.id, limit=2)
    assert all(c.provider == FAKE_PROVIDER_NAME for c in candidates)


def test_openai_provider_returns_candidates(monkeypatch, client, db):
    monkeypatch.setenv("SEARCH_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cluster = _cluster(db)
    expected = [MagicMock(provider="openai-web-search")]
    from app.services.retrieval import retrieve_resources_for_cluster
    with patch("app.services.retrieval._openai_search", return_value=expected) as search:
        candidates = retrieve_resources_for_cluster(db, cluster.id, limit=2)
    assert candidates == expected
    search.assert_called_once_with("Artificial Intelligence", 2, api_key="sk-test")
