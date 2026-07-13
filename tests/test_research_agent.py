"""Tests for the research agent — no real API keys required.

Unit tests mock Tavily and OpenAI. Integration tests use the real test DB
but mock all HTTP/AI calls so no network access is needed.
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.services.research_agent import (
    ResearchNotes,
    _execute_read_article,
    _execute_search_web,
    _fetch_article_content,
    run_research,
    AGENT_PROVIDER_NAME,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cluster_with_capture(db):
    from app.models.cluster import ClusterORM, ClusterItemORM
    from app.models.capture import CaptureORM

    cap = CaptureORM(
        id=str(uuid.uuid4()),
        source_type="article",
        label="return",
        status="extracted",
        url="https://example.com/test",
        title="Test Article",
        extracted_text="Some extracted content about neural networks.",
        user_note="Why does this work?",
    )
    db.add(cap)
    db.flush()

    cluster = ClusterORM(
        id=str(uuid.uuid4()),
        title="Neural Networks",
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

    # Reload with relationships
    db.expire_all()
    from sqlalchemy import select
    from app.models.cluster import ClusterORM as C
    return db.scalar(select(C).where(C.id == cluster.id))


def _make_openai_finish_response(summary="Research summary.", key_findings=None):
    """Build a mock OpenAI response that calls finish() immediately."""
    finish_args = {
        "summary": summary,
        "key_findings": key_findings or ["Finding one.", "Finding two."],
        "questions_answered": ["What is it?"],
        "questions_remaining": ["How to apply?"],
        "sources_used": ["https://example.com/article"],
    }

    tool_call = MagicMock()
    tool_call.id = "call_finish_001"
    tool_call.function.name = "finish"
    tool_call.function.arguments = json.dumps(finish_args)

    msg = MagicMock()
    msg.content = None
    msg.tool_calls = [tool_call]

    choice = MagicMock()
    choice.message = msg

    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    usage.total_tokens = 150

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _make_openai_search_then_finish_response(query="neural networks"):
    """First call returns search_web, second returns finish."""
    # search_web call
    tc_search = MagicMock()
    tc_search.id = "call_search_001"
    tc_search.function.name = "search_web"
    tc_search.function.arguments = json.dumps({"query": query, "max_results": 5})

    msg_search = MagicMock()
    msg_search.content = None
    msg_search.tool_calls = [tc_search]

    choice_search = MagicMock()
    choice_search.message = msg_search

    # finish call
    finish_args = {
        "summary": "Found info about neural networks.",
        "key_findings": ["Networks use layers."],
        "questions_answered": ["How do they work?"],
        "questions_remaining": [],
        "sources_used": [],
    }
    tc_finish = MagicMock()
    tc_finish.id = "call_finish_001"
    tc_finish.function.name = "finish"
    tc_finish.function.arguments = json.dumps(finish_args)

    msg_finish = MagicMock()
    msg_finish.content = None
    msg_finish.tool_calls = [tc_finish]

    choice_finish = MagicMock()
    choice_finish.message = msg_finish

    usage = MagicMock()
    usage.prompt_tokens = 200
    usage.completion_tokens = 100
    usage.total_tokens = 300

    resp_search = MagicMock()
    resp_search.choices = [choice_search]
    resp_search.usage = usage

    resp_finish = MagicMock()
    resp_finish.choices = [choice_finish]
    resp_finish.usage = usage

    return [resp_search, resp_finish]


def _make_openai_search_read_finish(url="https://example.com/article"):
    """Three turns: search_web → read_article → finish."""
    tc_search = MagicMock()
    tc_search.id = "call_search_001"
    tc_search.function.name = "search_web"
    tc_search.function.arguments = json.dumps({"query": "neural networks", "max_results": 5})
    msg1 = MagicMock(); msg1.content = None; msg1.tool_calls = [tc_search]
    r1 = MagicMock(); r1.choices = [MagicMock(message=msg1)]; r1.usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)

    tc_read = MagicMock()
    tc_read.id = "call_read_001"
    tc_read.function.name = "read_article"
    tc_read.function.arguments = json.dumps({"url": url})
    msg2 = MagicMock(); msg2.content = None; msg2.tool_calls = [tc_read]
    r2 = MagicMock(); r2.choices = [MagicMock(message=msg2)]; r2.usage = MagicMock(prompt_tokens=200, completion_tokens=50, total_tokens=250)

    finish_args = {
        "summary": "Deep research on neural networks complete.",
        "key_findings": ["Backprop is key.", "Layers matter."],
        "questions_answered": ["How do NNs learn?"],
        "questions_remaining": ["What about transformers?"],
        "sources_used": [url],
    }
    tc_finish = MagicMock()
    tc_finish.id = "call_finish_001"
    tc_finish.function.name = "finish"
    tc_finish.function.arguments = json.dumps(finish_args)
    msg3 = MagicMock(); msg3.content = None; msg3.tool_calls = [tc_finish]
    r3 = MagicMock(); r3.choices = [MagicMock(message=msg3)]; r3.usage = MagicMock(prompt_tokens=300, completion_tokens=100, total_tokens=400)

    return [r1, r2, r3]


# ---------------------------------------------------------------------------
# _execute_search_web — pure unit tests
# ---------------------------------------------------------------------------

def test_execute_search_web_returns_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    fake_candidates = [
        MagicMock(url="https://ex.com/1", title="Result 1", snippet="Snippet 1"),
        MagicMock(url="https://ex.com/2", title="Result 2", snippet="Snippet 2"),
    ]
    with patch("app.services.research_agent._tavily_search", return_value=fake_candidates):
        result = _execute_search_web("neural networks", 5)

    assert len(result["results"]) == 2
    assert result["results"][0]["url"] == "https://ex.com/1"
    assert result["results"][0]["title"] == "Result 1"
    assert "error" not in result or result.get("error") is None


def test_execute_search_web_returns_empty_on_tavily_failure(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    with patch("app.services.research_agent._tavily_search", side_effect=Exception("timeout")):
        result = _execute_search_web("query", 5)

    assert result["results"] == []
    assert "error" in result


def test_execute_search_web_no_key_returns_error(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)

    result = _execute_search_web("query", 5)

    assert result["results"] == []
    assert result["error"] == "no_search_api_key_configured"


# ---------------------------------------------------------------------------
# _fetch_article_content / _execute_read_article — unit tests
# ---------------------------------------------------------------------------

def test_fetch_article_content_uses_trafilatura(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    with patch("trafilatura.fetch_url", return_value="<html>content</html>") as mock_fetch, \
         patch("trafilatura.extract", return_value="Clean article text here " * 20) as mock_extract:
        content = _fetch_article_content("https://example.com/article")

    assert content is not None
    assert "Clean article text" in content


def test_fetch_article_content_falls_back_to_beautifulsoup(monkeypatch):
    html = "<html><nav>Nav</nav><article>Real content here</article></html>"
    mock_response = MagicMock()
    mock_response.text = html
    mock_response.raise_for_status = MagicMock()

    with patch("trafilatura.fetch_url", return_value=None), \
         patch("app.services.research_agent.requests.get", return_value=mock_response):
        content = _fetch_article_content("https://example.com/article")

    assert content is not None
    assert "Real content" in content


def test_execute_read_article_returns_error_on_fetch_failure(monkeypatch):
    with patch("trafilatura.fetch_url", return_value=None), \
         patch("app.services.research_agent.requests.get", side_effect=Exception("connection refused")):
        result = _execute_read_article("https://example.com/bad")

    assert result["content"] == ""
    assert result["error"] is not None


def test_execute_read_article_truncates_long_content(monkeypatch):
    long_text = "word " * 10_000  # way over 8000 chars
    with patch("app.services.research_agent._fetch_article_content", return_value=long_text):
        result = _execute_read_article("https://example.com/long")

    assert len(result["content"]) <= 8_001 + 1  # 8000 + "…"
    assert result["content"].endswith("…")


# ---------------------------------------------------------------------------
# run_research guards — unit tests
# ---------------------------------------------------------------------------

def test_run_research_returns_none_when_no_openai_key(monkeypatch, db):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    cluster = _make_cluster_with_capture(db)
    result = run_research(db, cluster)

    assert result is None


def test_run_research_returns_none_when_no_search_key(monkeypatch, db):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)

    cluster = _make_cluster_with_capture(db)
    result = run_research(db, cluster)

    assert result is None


# ---------------------------------------------------------------------------
# run_research integration tests — mock OpenAI, real DB
# ---------------------------------------------------------------------------

def test_run_research_finish_terminates_immediately(monkeypatch, db):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    cluster = _make_cluster_with_capture(db)
    resp = _make_openai_finish_response()

    with patch("app.services.research_agent.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = resp
        mock_openai_cls.return_value = mock_client

        notes = run_research(db, cluster)

    assert notes is not None
    assert notes.iterations_used == 1
    assert notes.summary == "Research summary."
    assert len(notes.key_findings) == 2


def test_run_research_max_iterations_exits_without_finish(monkeypatch, db):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("RESEARCH_MAX_ITERATIONS", "3")

    cluster = _make_cluster_with_capture(db)

    # Always return search_web, never finish
    tc = MagicMock()
    tc.id = "call_search_inf"
    tc.function.name = "search_web"
    tc.function.arguments = json.dumps({"query": "test"})
    msg = MagicMock(); msg.content = None; msg.tool_calls = [tc]
    resp = MagicMock(); resp.choices = [MagicMock(message=msg)]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    with patch("app.services.research_agent.OpenAI") as mock_openai_cls, \
         patch("app.services.research_agent._tavily_search", return_value=[]):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = resp
        mock_openai_cls.return_value = mock_client

        notes = run_research(db, cluster)

    assert notes is None
    assert mock_client.chat.completions.create.call_count == 3


def test_run_research_stores_resource_on_read_article(monkeypatch, db):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    cluster = _make_cluster_with_capture(db)
    article_url = "https://example.com/neural-nets"
    responses = _make_openai_search_read_finish(url=article_url)

    fake_search_results = [
        MagicMock(url=article_url, title="Neural Nets Guide", snippet="Great guide.")
    ]

    with patch("app.services.research_agent.OpenAI") as mock_openai_cls, \
         patch("app.services.research_agent._tavily_search", return_value=fake_search_results), \
         patch("app.services.research_agent._fetch_article_content", return_value="Full article text about neural nets " * 50):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = responses
        mock_openai_cls.return_value = mock_client

        notes = run_research(db, cluster)

    assert notes is not None
    assert article_url in notes.sources_used

    from app.services.resource_store import list_resources_for_cluster
    resources = list_resources_for_cluster(db, cluster.id)
    assert any(r.url == article_url for r in resources)
    assert any(r.provider == AGENT_PROVIDER_NAME for r in resources)


def test_run_research_skips_duplicate_resource(monkeypatch, db):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    cluster = _make_cluster_with_capture(db)
    article_url = "https://example.com/dup"

    # Pre-seed the resource
    from app.schemas.resource import Resource
    from app.services import resource_store
    resource_store.create_resource(db, Resource(
        cluster_id=cluster.id,
        url=article_url,
        title="Pre-existing",
        source_type="article",
        provider="tavily",
        relevance_score=0.8,
        validation_score=0.8,
        validation_reason="pre-seeded",
    ))

    responses = _make_openai_search_read_finish(url=article_url)
    fake_search = [MagicMock(url=article_url, title="Dup Article", snippet="...")]

    with patch("app.services.research_agent.OpenAI") as mock_openai_cls, \
         patch("app.services.research_agent._tavily_search", return_value=fake_search), \
         patch("app.services.research_agent._fetch_article_content", return_value="content " * 100):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = responses
        mock_openai_cls.return_value = mock_client

        notes = run_research(db, cluster)

    # No IntegrityError raised; resource count stays at 1
    from app.services.resource_store import list_resources_for_cluster
    assert len(list_resources_for_cluster(db, cluster.id)) == 1


def test_run_research_records_llm_call_telemetry(monkeypatch, db):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    cluster = _make_cluster_with_capture(db)
    resp = _make_openai_finish_response()

    with patch("app.services.research_agent.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = resp
        mock_openai_cls.return_value = mock_client

        run_research(db, cluster, job_id="test-job-001")

    from sqlalchemy import select, text
    rows = db.execute(
        text("SELECT purpose, owner_id FROM llm_calls WHERE purpose = 'research_agent'")
    ).fetchall()
    assert len(rows) >= 1
    assert any(r[1] == cluster.id for r in rows)


def test_run_research_records_retrieval_event_on_search(monkeypatch, db):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    cluster = _make_cluster_with_capture(db)
    responses = _make_openai_search_then_finish_response()
    fake_search = [MagicMock(url="https://ex.com/1", title="T1", snippet="S1")]

    with patch("app.services.research_agent.OpenAI") as mock_openai_cls, \
         patch("app.services.research_agent._tavily_search", return_value=fake_search):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = responses
        mock_openai_cls.return_value = mock_client

        run_research(db, cluster, job_id="test-job-002")

    from sqlalchemy import text
    rows = db.execute(
        text("SELECT cluster_id, provider FROM retrieval_events WHERE cluster_id = :cid"),
        {"cid": cluster.id},
    ).fetchall()
    assert len(rows) >= 1
    assert rows[0][1] == "tavily"


def test_run_research_returns_structured_notes_fields(monkeypatch, db):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    cluster = _make_cluster_with_capture(db)
    resp = _make_openai_finish_response(
        summary="Detailed summary here.",
        key_findings=["Finding A.", "Finding B.", "Finding C."],
    )

    with patch("app.services.research_agent.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = resp
        mock_openai_cls.return_value = mock_client

        notes = run_research(db, cluster)

    assert isinstance(notes, ResearchNotes)
    assert notes.summary == "Detailed summary here."
    assert notes.key_findings == ["Finding A.", "Finding B.", "Finding C."]
    assert notes.questions_answered == ["What is it?"]
    assert notes.questions_remaining == ["How to apply?"]
    assert notes.sources_used == ["https://example.com/article"]
    assert notes.iterations_used == 1
    assert "gpt-4o-mini" in notes.model
