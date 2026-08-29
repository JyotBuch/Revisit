import json
from unittest.mock import MagicMock, patch

from app.services.openai_search import OPENAI_SEARCH_PROVIDER, search_web


def _response(payload):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def test_search_web_uses_only_visited_sources(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    output = json.dumps({"results": [
        {"url": "https://example.com/real", "title": "Real", "snippet": "Verified source."},
        {"url": "https://invented.example/fake", "title": "Fake", "snippet": "Nope."},
    ]})
    payload = {"output": [
        {"type": "web_search_call", "action": {"sources": [
            {"url": "https://example.com/real?utm_source=openai", "title": "Visited title"}]}},
        {"type": "message", "content": [{"type": "output_text", "text": output, "annotations": []}]},
    ]}
    with patch("app.services.openai_search.requests.post", return_value=_response(payload)) as post:
        results = search_web("test query", 3)
    assert len(results) == 1
    assert results[0].url == "https://example.com/real?utm_source=openai"
    assert results[0].title == "Real"
    assert results[0].snippet == "Verified source."
    assert results[0].provider == OPENAI_SEARCH_PROVIDER
    request = post.call_args.kwargs
    assert request["json"]["tools"] == [{"type": "web_search"}]
    assert request["json"]["tool_choice"] == "required"


def test_search_web_falls_back_to_citation_metadata_on_bad_json(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    payload = {"output": [{"type": "message", "content": [{
        "type": "output_text", "text": "not json", "annotations": [{
            "type": "url_citation", "url": "https://example.com/source", "title": "Source"}]
    }]}]}
    with patch("app.services.openai_search.requests.post", return_value=_response(payload)):
        results = search_web("test", 2)
    assert [(r.url, r.title) for r in results] == [("https://example.com/source", "Source")]


def test_search_web_without_key_does_not_call_network(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with patch("app.services.openai_search.requests.post") as post:
        assert search_web("test") == []
    post.assert_not_called()
