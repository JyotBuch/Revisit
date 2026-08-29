"""Agentic research loop for return-labeled clusters.

Runs a tool-calling loop using the OpenAI SDK: the model decides what to
search, which articles to read in full, and when it has enough to call
finish() with structured research notes.

The loop is the replacement for the single-search + keyword-validation
path when generation_method=llm and both OPENAI_API_KEY and a search key are
configured. When either key is absent, run_research() returns None and the
batch job falls back to the existing retrieval path.

Tools exposed to the model:
  search_web(query, max_results) — OpenAI web search, returns title/url/snippet
  read_article(url)              — fetches full article text, stores as resource
  finish(...)                    — terminates the loop, returns ResearchNotes
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests
from openai import OpenAI
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.cluster import ClusterORM
from app.schemas.resource import Resource, ResourceCandidate
from app.services import resource_store, telemetry
from app.services.langfuse_client import get_langfuse
from app.services.openai_search import OPENAI_SEARCH_PROVIDER, search_web

logger = logging.getLogger("revisit.research_agent")

DEFAULT_RESEARCH_MODEL = "gpt-4o-mini"
RESEARCH_PROMPT_VERSION = "v1"
AGENT_PROVIDER_NAME = "research-agent-v1"
_DEFAULT_MAX_ITERATIONS = 6
_DEFAULT_SEARCH_RESULTS = 5
_MAX_ARTICLE_CHARS = 8_000
_MAX_CAPTURE_TEXT_CHARS = 2_000
_MAX_CAPTURES_IN_PROMPT = 5


@dataclass
class ResearchNotes:
    summary: str
    key_findings: List[str] = field(default_factory=list)
    questions_answered: List[str] = field(default_factory=list)
    questions_remaining: List[str] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)
    iterations_used: int = 0
    model: str = DEFAULT_RESEARCH_MODEL


_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Search the web for articles or resources relevant to the research topic. "
                "Returns a list of results with title, url, and snippet. "
                "Use specific, targeted queries rather than just the cluster title verbatim."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query string.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max number of results to return (1-10). Default 5.",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_article",
            "description": (
                "Fetch and extract the full text content of a specific article URL. "
                "Use this after search_web to read a promising result in depth. "
                "Only call this for URLs returned by search_web — do not invent URLs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL of the article to read.",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "Signal that research is complete and return structured notes. "
                "Call this when you have enough information to produce useful notes, "
                "or when further searching would not add value. "
                "You MUST have called search_web and read_article at least once before finish."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": (
                            "A 2-4 paragraph synthesis of what was found. "
                            "This becomes the primary source for the user's Revisit Card. "
                            "Be concrete, actionable, and honest about gaps."
                        ),
                    },
                    "key_findings": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "3-7 specific, concrete findings. Each is a complete sentence.",
                    },
                    "questions_answered": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The specific questions or aspects that were successfully researched.",
                    },
                    "questions_remaining": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Open questions that need more research. Empty if coverage is thorough.",
                    },
                    "sources_used": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of URLs that were actually read via read_article.",
                    },
                },
                "required": [
                    "summary",
                    "key_findings",
                    "questions_answered",
                    "questions_remaining",
                    "sources_used",
                ],
            },
        },
    },
]

_SYSTEM_PROMPT = """\
You are a focused research assistant for a knowledge management tool. A user has \
been saving captures (bookmarks, passages, notes) about a topic and wants to learn \
more about it. Your job is to research the topic thoroughly and produce structured \
research notes that will be used to write a Revisit Card — a concise brief that \
helps the user resume the topic later.

You have three tools:
- search_web: Search the web with a specific query
- read_article: Fetch and read the full content of a URL returned by search_web
- finish: Return your structured research notes and end the session

Research process:
1. Analyze the cluster topic and the user's saves to understand their intent — \
   what are they trying to learn, build, or solve?
2. Generate 1-2 targeted search queries. Be specific; do not repeat the cluster \
   title verbatim. Focus on the user's implicit question.
3. Review the search results and identify the 2-3 most promising URLs.
4. Use read_article to read those URLs in depth — not just their snippets.
5. If you discover new angles or gaps after reading, do one follow-up search.
6. Call finish() with a thorough synthesis.

Rules:
- Never reference a source you did not read via read_article.
- Do not make up facts, URLs, or author names.
- Keep findings concrete and specific, not generic summaries.
- The finish() summary will be used directly to write a Revisit Card.
- You MUST call finish() to conclude. The loop ends after a fixed number of iterations.
"""


def _get_max_iterations() -> int:
    try:
        return int(os.environ.get("RESEARCH_MAX_ITERATIONS", _DEFAULT_MAX_ITERATIONS))
    except ValueError:
        return _DEFAULT_MAX_ITERATIONS


def _get_model() -> str:
    return os.environ.get("OPENAI_RESEARCH_MODEL", DEFAULT_RESEARCH_MODEL)


def _fetch_article_content(url: str, timeout: int = 15) -> Optional[str]:
    """Fetch article text. Tries trafilatura first for clean extraction, falls back to BS4."""
    try:
        import trafilatura  # type: ignore
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                favor_precision=True,
            )
            if text and len(text) > 200:
                return text
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("trafilatura_failed url=%s error=%s", url, exc)

    try:
        from bs4 import BeautifulSoup
        response = requests.get(
            url, timeout=timeout, headers={"User-Agent": "RevisitBot/0.1"}
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return text if text else None
    except Exception as exc:
        logger.debug("bs4_fetch_failed url=%s error=%s", url, exc)
        return None


def _execute_search_web(query: str, max_results: int) -> Dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"error": "no_search_api_key_configured", "results": []}
    try:
        candidates = search_web(query, max_results, api_key=api_key)
        return {
            "results": [
                {"url": c.url, "title": c.title, "snippet": c.snippet or ""}
                for c in candidates
            ]
        }
    except Exception as exc:
        logger.info("research_agent_search_failed query=%s error=%s", query, exc)
        return {"error": f"{type(exc).__name__}: {exc}", "results": []}


def _execute_read_article(url: str) -> Dict[str, Any]:
    try:
        content = _fetch_article_content(url)
        if not content:
            return {"url": url, "content": "", "error": "no_content_extracted"}
        truncated = content[:_MAX_ARTICLE_CHARS]
        if len(content) > _MAX_ARTICLE_CHARS:
            truncated += "…"
        return {"url": url, "content": truncated, "error": None}
    except Exception as exc:
        return {"url": url, "content": "", "error": f"{type(exc).__name__}: {exc}"}


def _store_resource_from_read(
    db: Session,
    cluster_id: str,
    url: str,
    url_metadata: Dict[str, Dict[str, str]],
    read_result: Dict[str, Any],
) -> None:
    existing = resource_store.get_resource_urls_for_cluster(db, cluster_id)
    if url in existing:
        return

    meta = url_metadata.get(url, {})
    content = read_result.get("content", "")
    title = meta.get("title") or url
    snippet = meta.get("snippet") or content[:500]
    query = meta.get("query", "")

    resource = Resource(
        cluster_id=cluster_id,
        url=url,
        title=title,
        source_type="article",
        snippet=snippet[:2000] if snippet else None,
        query=query[:500] if query else None,
        relevance_score=1.0,
        validation_score=1.0,
        validation_reason="agent_read: research agent explicitly fetched and read this article",
        provider=AGENT_PROVIDER_NAME,
    )
    try:
        resource_store.create_resource(db, resource)
    except IntegrityError:
        db.rollback()
        logger.debug(
            "research_agent_resource_duplicate url=%s cluster_id=%s", url, cluster_id
        )


def _record_llm_call(
    db: Session,
    job_id: Optional[str],
    cluster_id: str,
    model: str,
    *,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    latency_ms: int,
    status: str,
    failure_type: Optional[str] = None,
) -> None:
    try:
        telemetry.record_llm_call(
            db,
            job_id=job_id,
            owner_type="cluster",
            owner_id=cluster_id,
            purpose="research_agent",
            model_name=model,
            prompt_version=RESEARCH_PROMPT_VERSION,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            status=status,
            failure_type=failure_type,
        )
        db.commit()
    except Exception:
        logger.warning("research_agent_llm_telemetry_failed", exc_info=True)
        db.rollback()


def _record_retrieval_event(
    db: Session,
    job_id: Optional[str],
    cluster_id: str,
    query: str,
    num_results: int,
    latency_ms: int = 0,
) -> None:
    try:
        telemetry.record_retrieval_event(
            db,
            job_id=job_id,
            cluster_id=cluster_id,
            query=query[:500],
            provider=OPENAI_SEARCH_PROVIDER,
            num_candidates=num_results,
            num_accepted=num_results,
            latency_ms=latency_ms,
            status="succeeded",
        )
        db.commit()
    except Exception:
        logger.warning("research_agent_retrieval_telemetry_failed", exc_info=True)
        db.rollback()


def _build_initial_message(cluster: ClusterORM) -> str:
    parts = [f"Research topic: {cluster.title or 'Untitled Topic'}"]
    if cluster.description:
        parts.append(f"Topic description: {cluster.description}")
    parts.append("\nSaved captures in this topic:")

    for item in cluster.items[:_MAX_CAPTURES_IN_PROMPT]:
        cap = item.capture
        cap_parts = [f"\n- Title: {cap.title or 'Untitled'}"]
        if cap.url:
            cap_parts.append(f"  URL: {cap.url}")
        if cap.user_note:
            cap_parts.append(f"  User note: {cap.user_note[:500]}")
        if cap.selected_text:
            cap_parts.append(f"  Selected text: {cap.selected_text[:500]}")
        if cap.extracted_text:
            text = cap.extracted_text[:_MAX_CAPTURE_TEXT_CHARS]
            if len(cap.extracted_text) > _MAX_CAPTURE_TEXT_CHARS:
                text += "…"
            cap_parts.append(f"  Content excerpt: {text}")
        parts.append("\n".join(cap_parts))

    parts.append(
        "\nPlease research this topic thoroughly. Search for specific aspects, "
        "read 2-3 articles in depth, and produce research notes that will help "
        "me resume this topic later."
    )
    return "\n".join(parts)


def run_research(
    db: Session,
    cluster: ClusterORM,
    job_id: Optional[str] = None,
    limit: int = 5,
) -> Optional[ResearchNotes]:
    """Run the agentic research loop for a cluster.

    Returns ResearchNotes on success, None if prerequisites are missing or
    the agent fails to call finish() within the iteration budget.
    Callers must treat None as "fall back to existing retrieval path".
    """
    if not os.environ.get("OPENAI_API_KEY"):
        logger.debug("research_agent_skipped reason=no_openai_key cluster_id=%s", cluster.id)
        return None

    model = _get_model()
    max_iterations = _get_max_iterations()

    try:
        client = OpenAI()
    except Exception as exc:
        logger.warning("research_agent_client_init_failed cluster_id=%s error=%s", cluster.id, exc)
        return None

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_initial_message(cluster)},
    ]

    lf = get_langfuse()
    lf_trace = None
    if lf is not None:
        try:
            # v4 SDK: use start_observation(as_type="agent") for top-level trace
            lf_trace = lf.start_observation(
                name="research-agent",
                as_type="agent",
                input={
                    "cluster_id": cluster.id,
                    "cluster_title": cluster.title,
                    "job_id": job_id,
                },
                metadata={
                    "model": model,
                    "max_iterations": max_iterations,
                },
            )
        except Exception:
            lf_trace = None

    url_metadata: Dict[str, Dict[str, str]] = {}
    finish_result: Optional[Dict[str, Any]] = None
    iterations_used = 0

    for iteration in range(max_iterations):
        iterations_used = iteration + 1
        start = time.monotonic()

        lf_gen = None
        if lf_trace is not None:
            try:
                lf_gen = lf_trace.start_observation(
                    name=f"llm-call-{iteration + 1}",
                    as_type="generation",
                    model=model,
                    model_parameters={"tool_choice": "auto"},
                    input=messages,
                )
            except Exception:
                lf_gen = None

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                tools=_TOOLS,  # type: ignore[arg-type]
                tool_choice="auto",
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            _record_llm_call(
                db, job_id, cluster.id, model,
                latency_ms=latency_ms,
                status="failed",
                failure_type=type(exc).__name__,
            )
            if lf_gen is not None:
                try:
                    lf_gen.update(level="ERROR", status_message=str(exc))
                    lf_gen.end()
                except Exception:
                    pass
            logger.warning(
                "research_agent_llm_error cluster_id=%s iteration=%d error=%s",
                cluster.id, iteration, exc,
            )
            break

        latency_ms = int((time.monotonic() - start) * 1000)
        usage = response.usage
        _record_llm_call(
            db, job_id, cluster.id, model,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
            latency_ms=latency_ms,
            status="succeeded",
        )
        if lf_gen is not None:
            try:
                lf_gen.update(
                    output=response.choices[0].message.content,
                    usage_details={
                        "input": usage.prompt_tokens,
                        "output": usage.completion_tokens,
                        "total": usage.total_tokens,
                    } if usage else None,
                )
                lf_gen.end()
            except Exception:
                pass

        assistant_msg = response.choices[0].message

        # Serialize the assistant message as a dict for the next call.
        # content may be None when the model only returns tool calls.
        tool_calls_serialized = None
        if assistant_msg.tool_calls:
            tool_calls_serialized = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_msg.tool_calls
            ]

        messages.append({
            "role": "assistant",
            "content": assistant_msg.content,
            "tool_calls": tool_calls_serialized,
        })

        if not assistant_msg.tool_calls:
            logger.info(
                "research_agent_no_tool_calls cluster_id=%s iteration=%d", cluster.id, iteration
            )
            continue

        done = False
        tool_results: List[Dict[str, Any]] = []

        for tool_call in assistant_msg.tool_calls:
            fn_name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                args = {}

            if fn_name == "search_web":
                query = args.get("query", "")
                max_r = min(max(int(args.get("max_results", _DEFAULT_SEARCH_RESULTS)), 1), 10)
                lf_span = None
                if lf_trace is not None:
                    try:
                        lf_span = lf_trace.start_observation(
                            name="search_web",
                            as_type="retriever",
                            input={"query": query, "max_results": max_r},
                        )
                    except Exception:
                        pass
                t0 = time.monotonic()
                result = _execute_search_web(query, max_r)
                search_latency = int((time.monotonic() - t0) * 1000)
                for r in result.get("results", []):
                    url_metadata[r["url"]] = {
                        "title": r.get("title", ""),
                        "snippet": r.get("snippet", ""),
                        "query": query,
                    }
                _record_retrieval_event(
                    db, job_id, cluster.id, query,
                    num_results=len(result.get("results", [])),
                    latency_ms=search_latency,
                )
                if lf_span is not None:
                    try:
                        lf_span.update(output={
                            "num_results": len(result.get("results", [])),
                            "error": result.get("error"),
                        })
                        lf_span.end()
                    except Exception:
                        pass
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                })

            elif fn_name == "read_article":
                url = args.get("url", "")
                lf_span = None
                if lf_trace is not None:
                    try:
                        lf_span = lf_trace.start_observation(
                            name="read_article",
                            as_type="tool",
                            input={"url": url},
                        )
                    except Exception:
                        pass
                read_result = _execute_read_article(url)
                _store_resource_from_read(db, cluster.id, url, url_metadata, read_result)
                if lf_span is not None:
                    try:
                        lf_span.update(output={
                            "chars_extracted": len(read_result.get("content", "")),
                            "error": read_result.get("error"),
                        })
                        lf_span.end()
                    except Exception:
                        pass
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({
                        "url": url,
                        "content": read_result.get("content", ""),
                        "error": read_result.get("error"),
                    }),
                })

            elif fn_name == "finish":
                finish_result = args
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"status": "research_complete"}),
                })
                done = True
                break

        messages.extend(tool_results)

        if done:
            break

    if finish_result is None:
        logger.info(
            "research_agent_no_finish cluster_id=%s iterations_used=%d",
            cluster.id, iterations_used,
        )
        if lf_trace is not None:
            try:
                lf_trace.update(
                    output={"status": "no_finish_called", "iterations_used": iterations_used},
                    level="WARNING",
                )
                lf_trace.end()
                lf.flush()  # type: ignore[union-attr]
            except Exception:
                pass
        return None

    notes = ResearchNotes(
        summary=finish_result.get("summary", ""),
        key_findings=finish_result.get("key_findings", []),
        questions_answered=finish_result.get("questions_answered", []),
        questions_remaining=finish_result.get("questions_remaining", []),
        sources_used=finish_result.get("sources_used", []),
        iterations_used=iterations_used,
        model=model,
    )
    if lf_trace is not None:
        try:
            lf_trace.update(output={
                "summary": notes.summary[:500],
                "key_findings_count": len(notes.key_findings),
                "sources_used": notes.sources_used,
                "iterations_used": iterations_used,
            })
            lf_trace.end()
            lf.flush()  # type: ignore[union-attr]
        except Exception:
            pass
    return notes
