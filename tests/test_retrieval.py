"""Tests for the retrieval service — no real API key required.

Covers:
- no key configured → fake provider used
- SEARCH_PROVIDER=tavily with no key → fake provider fallback
- Tavily response normalisation via mocked requests.post
- _get_api_key prefers TAVILY_API_KEY over SEARCH_API_KEY
- Brave fallback still works (backward compat)
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.retrieval import (
    FAKE_PROVIDER_NAME,
    _get_api_key,
    _tavily_search,
    _fake_resources_for_query,
)


# ---------------------------------------------------------------------------
# _get_api_key
# ---------------------------------------------------------------------------

def test_get_api_key_tavily_prefers_tavily_key(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-primary")
    monkeypatch.setenv("SEARCH_API_KEY", "generic-fallback")
    assert _get_api_key("tavily") == "tvly-primary"


def test_get_api_key_tavily_falls_back_to_search_api_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("SEARCH_API_KEY", "generic-fallback")
    assert _get_api_key("tavily") == "generic-fallback"


def test_get_api_key_tavily_returns_none_when_neither_set(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    assert _get_api_key("tavily") is None


def test_get_api_key_brave_uses_search_api_key_only(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-should-be-ignored")
    monkeypatch.setenv("SEARCH_API_KEY", "brave-key")
    assert _get_api_key("brave") == "brave-key"


# ---------------------------------------------------------------------------
# _tavily_search — mocked HTTP
# ---------------------------------------------------------------------------

def _make_tavily_response(results):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"results": results}
    return mock_resp


def test_tavily_search_normalises_response():
    fake_results = [
        {
            "url": "https://example.com/article-1",
            "title": "Neural Networks Explained",
            "content": "A beginner's guide to neural networks.",
        },
        {
            "url": "https://example.com/article-2",
            "title": "Deep Learning Foundations",
            "content": "Core concepts of deep learning.",
        },
    ]
    with patch("app.services.retrieval.requests.post") as mock_post:
        mock_post.return_value = _make_tavily_response(fake_results)
        candidates = _tavily_search("neural networks", limit=5, api_key="tvly-test")

    assert len(candidates) == 2
    assert candidates[0].url == "https://example.com/article-1"
    assert candidates[0].title == "Neural Networks Explained"
    assert candidates[0].snippet == "A beginner's guide to neural networks."
    assert candidates[0].provider == "tavily"
    assert candidates[0].query == "neural networks"
    assert candidates[0].source_type == "article"


def test_tavily_search_skips_items_missing_url_or_title():
    fake_results = [
        {"url": "https://example.com/ok", "title": "Good Result", "content": "..."},
        {"url": "", "title": "Missing URL"},
        {"url": "https://example.com/missing-title", "title": ""},
    ]
    with patch("app.services.retrieval.requests.post") as mock_post:
        mock_post.return_value = _make_tavily_response(fake_results)
        candidates = _tavily_search("query", limit=5, api_key="tvly-test")

    assert len(candidates) == 1
    assert candidates[0].url == "https://example.com/ok"


def test_tavily_search_respects_limit():
    fake_results = [
        {"url": f"https://example.com/{i}", "title": f"Result {i}", "content": "x"}
        for i in range(10)
    ]
    with patch("app.services.retrieval.requests.post") as mock_post:
        mock_post.return_value = _make_tavily_response(fake_results)
        candidates = _tavily_search("query", limit=3, api_key="tvly-test")

    assert len(candidates) == 3


def test_tavily_search_sends_correct_payload():
    with patch("app.services.retrieval.requests.post") as mock_post:
        mock_post.return_value = _make_tavily_response([])
        _tavily_search("machine learning", limit=5, api_key="tvly-key")

    call_kwargs = mock_post.call_args
    payload = call_kwargs[1]["json"]
    assert payload["query"] == "machine learning"
    assert payload["api_key"] == "tvly-key"
    assert payload["max_results"] == 5
    assert payload["include_answer"] is False
    assert payload["include_images"] is False


# ---------------------------------------------------------------------------
# retrieve_resources_for_cluster — integration-level with real DB
# ---------------------------------------------------------------------------

def test_no_provider_configured_uses_fake(client, db):
    """With no SEARCH_PROVIDER set, retrieval must use the fake provider."""
    # conftest already pops SEARCH_PROVIDER / TAVILY_API_KEY / SEARCH_API_KEY
    import uuid
    from app.models.cluster import ClusterORM, ClusterItemORM
    from app.models.capture import CaptureORM

    cap = CaptureORM(
        id=str(uuid.uuid4()),
        source_type="article",
        label="return",
        status="extracted",
        url="https://example.com/ai",
        title="Introduction to AI",
        extracted_text="Artificial intelligence basics",
    )
    db.add(cap)
    db.flush()

    cluster = ClusterORM(
        id=str(uuid.uuid4()),
        title="Artificial Intelligence",
        status="active",
    )
    db.add(cluster)
    db.flush()

    item = ClusterItemORM(
        id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        capture_id=cap.id,
    )
    db.add(item)
    db.commit()

    from app.services.retrieval import retrieve_resources_for_cluster
    candidates = retrieve_resources_for_cluster(db, cluster.id, limit=3)

    assert candidates is not None
    assert len(candidates) == 3
    assert all(c.provider == FAKE_PROVIDER_NAME for c in candidates)


def test_tavily_provider_no_key_falls_back_to_fake(monkeypatch, client, db):
    """SEARCH_PROVIDER=tavily but no key → falls back to fake provider."""
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)

    import uuid
    from app.models.cluster import ClusterORM, ClusterItemORM
    from app.models.capture import CaptureORM

    cap = CaptureORM(
        id=str(uuid.uuid4()),
        source_type="article",
        label="return",
        status="extracted",
        url="https://example.com/ml",
        title="Machine Learning Overview",
        extracted_text="Machine learning fundamentals",
    )
    db.add(cap)
    db.flush()

    cluster = ClusterORM(
        id=str(uuid.uuid4()),
        title="Machine Learning",
        status="active",
    )
    db.add(cluster)
    db.flush()

    item = ClusterItemORM(
        id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        capture_id=cap.id,
    )
    db.add(item)
    db.commit()

    from app.services.retrieval import retrieve_resources_for_cluster
    candidates = retrieve_resources_for_cluster(db, cluster.id, limit=2)

    assert candidates is not None
    assert all(c.provider == FAKE_PROVIDER_NAME for c in candidates)


def test_tavily_provider_http_failure_falls_back_to_fake(monkeypatch, client, db):
    """SEARCH_PROVIDER=tavily with key but HTTP failure → fallback to fake."""
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-bad-key")

    import uuid
    from app.models.cluster import ClusterORM, ClusterItemORM
    from app.models.capture import CaptureORM

    cap = CaptureORM(
        id=str(uuid.uuid4()),
        source_type="article",
        label="return",
        status="extracted",
        url="https://example.com/nlp",
        title="NLP Research",
        extracted_text="Natural language processing research",
    )
    db.add(cap)
    db.flush()

    cluster = ClusterORM(
        id=str(uuid.uuid4()),
        title="NLP Research",
        status="active",
    )
    db.add(cluster)
    db.flush()

    item = ClusterItemORM(
        id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        capture_id=cap.id,
    )
    db.add(item)
    db.commit()

    from app.services.retrieval import retrieve_resources_for_cluster
    with patch("app.services.retrieval.requests.post") as mock_post:
        mock_post.side_effect = Exception("connection refused")
        candidates = retrieve_resources_for_cluster(db, cluster.id, limit=2)

    assert candidates is not None
    assert all(c.provider == FAKE_PROVIDER_NAME for c in candidates)
