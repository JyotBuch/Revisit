"""OpenAI Responses API adapter for web source discovery."""

import json
import os
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from app.schemas.resource import ResourceCandidate

OPENAI_SEARCH_PROVIDER = "openai-web-search"
DEFAULT_OPENAI_SEARCH_MODEL = "gpt-4o-mini"


def _canonical_url(url: str) -> str:
    """Ignore OpenAI's attribution parameter when matching returned citations."""
    parts = urlsplit(url)
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query) if key != "utm_source"])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _response_text(payload: dict[str, Any]) -> str:
    for item in payload.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                return str(content["text"])
    return ""


def _visited_sources(payload: dict[str, Any]) -> dict[str, str]:
    """Return URL -> title for sources the hosted search tool actually visited."""
    sources: dict[str, str] = {}
    for item in payload.get("output") or []:
        if item.get("type") == "web_search_call":
            for source in (item.get("action") or {}).get("sources") or []:
                url = source.get("url")
                if url:
                    sources[str(url)] = str(source.get("title") or url)
        if item.get("type") == "message":
            for content in item.get("content") or []:
                for annotation in content.get("annotations") or []:
                    if annotation.get("type") != "url_citation":
                        continue
                    url = annotation.get("url")
                    if url:
                        sources[str(url)] = str(annotation.get("title") or url)
    return sources


def search_web(query: str, limit: int = 5, *, api_key: str | None = None) -> list[ResourceCandidate]:
    """Search with OpenAI and normalize visited sources into ResourceCandidate objects."""
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        return []

    limit = min(max(limit, 1), 10)
    schema = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "maxItems": limit,
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "snippet": {"type": "string"},
                    },
                    "required": ["url", "title", "snippet"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": os.environ.get("OPENAI_SEARCH_MODEL", DEFAULT_OPENAI_SEARCH_MODEL),
            "input": (
                f"Search the web for: {query}\n"
                f"Return up to {limit} relevant, credible results. Use only URLs actually found "
                "with web search. Make each snippet a concise factual description of that source."
            ),
            "tools": [{"type": "web_search"}],
            "tool_choice": "required",
            "include": ["web_search_call.action.sources"],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "web_search_results",
                    "strict": True,
                    "schema": schema,
                }
            },
            "max_tool_calls": 3,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    visited = _visited_sources(payload)

    described: list[dict[str, str]] = []
    try:
        for row in json.loads(_response_text(payload)).get("results", []):
            url = str(row.get("url") or "")
            described.append(row)
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass

    visited_by_canonical = {_canonical_url(url): url for url in visited}
    selected: list[tuple[str, dict[str, str]]] = []
    used: set[str] = set()
    for row in described:
        url = visited_by_canonical.get(_canonical_url(str(row.get("url") or "")))
        if url and url not in used:
            selected.append((url, row))
            used.add(url)
    for url in visited:
        if len(selected) >= limit:
            break
        if url not in used:
            selected.append((url, {}))
            used.add(url)

    candidates = []
    for url, row in selected[:limit]:
        visited_title = visited[url]
        candidates.append(ResourceCandidate(
            url=url,
            title=str(row.get("title") or visited_title)[:500],
            source_type="article",
            snippet=str(row.get("snippet") or "")[:4000] or None,
            query=query,
            provider=OPENAI_SEARCH_PROVIDER,
        ))
    return candidates
