"""Related-resource retrieval for clusters.

Supports one real provider — Tavily Search, via SEARCH_PROVIDER=tavily +
TAVILY_API_KEY (or SEARCH_API_KEY as a legacy fallback) — and a
deterministic fake provider used whenever a real provider isn't configured
or the real call fails/returns nothing. Brave Search (SEARCH_PROVIDER=brave)
is kept for backward compatibility but Tavily is the recommended provider.

The fake provider is clearly development/testing only: it does not search the
web. It fabricates plausible-looking resource candidates derived from a hash
of the cluster's own title/context (the same pattern used for fake embeddings
elsewhere in this codebase), so the retrieve -> validate -> store loop can be
built and exercised end-to-end without a live search API key. Real and fake
candidates flow through the exact same validation step, so neither path gets
special treatment.

This does not scrape arbitrary pages — only a provider's own search result
metadata (url/title/snippet) is used, never page content.
"""

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional

import requests
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.cluster import ClusterORM
from app.schemas.resource import Resource, ResourceCandidate
from app.services import resource_store, telemetry
from app.services.clustering import get_cluster
from app.services.resource_validation import validate_resource_for_cluster

logger = logging.getLogger("revisit.retrieval")

FAKE_PROVIDER_NAME = "fake-local-dev-v1"
_SUPPORTED_REAL_PROVIDERS = {"tavily", "brave"}


@dataclass
class ResourceRetrievalSummary:
    resources_retrieved: int
    resources_accepted: int
    resources: List[Resource]


def generate_cluster_search_query(cluster: ClusterORM) -> str:
    if cluster.title and cluster.title != "Untitled Cluster":
        return cluster.title
    for item in cluster.items:
        capture = item.capture
        text = (
            capture.title
            or capture.user_note
            or capture.selected_text
            or capture.extracted_text
        )
        if text:
            return text[:100]
    return "general topic"


def _context_excerpt_for_fake_provider(cluster: ClusterORM) -> str:
    """Pulls real words out of the cluster's own captures so the fake
    provider's resource text shares vocabulary with the cluster by
    construction — a real search engine would return results that mention
    the query terms; this stand-in needs to do the same to be a usable
    test double for the validation step, not just a generic placeholder.
    """
    parts = [cluster.title or ""]
    for item in cluster.items:
        capture = item.capture
        parts.append(capture.title or "")
        parts.append(
            capture.user_note or capture.selected_text or capture.extracted_text or ""
        )
    excerpt = " ".join(p for p in parts if p)
    return excerpt[:300] if excerpt else "general topic"


def _fake_resources_for_query(
    query: str, context_excerpt: str, limit: int
) -> List[ResourceCandidate]:
    """Deterministic, NOT a real search — development/testing only.

    Derives plausible-looking resource candidates from a hash of the
    query, so the same cluster always yields the same fake resources. The
    URLs are fabricated and will not resolve to anything real. The
    title/snippet deliberately reuse words from context_excerpt (drawn
    from the cluster's own captures) rather than just the short query, so
    these candidates have genuine lexical overlap with the cluster to
    validate against — a fake provider that only echoed the 2-3-word query
    back would systematically fail the relevance check against a cluster's
    much richer context, which would make this fake provider useless for
    exercising the rest of the pipeline.
    """
    slug = "-".join(query.lower().split())[:40] or "topic"
    seed = int(hashlib.sha256(query.encode("utf-8")).hexdigest(), 16)
    candidates = []
    for i in range(limit):
        candidates.append(
            ResourceCandidate(
                url=f"https://example-dev-resource.local/{slug}-{(seed + i) % 100000}",
                title=f"[dev] {context_excerpt[:80]}" + (f" (#{i + 1})" if i else ""),
                source_type="article",
                snippet=(
                    f"[dev] Development-only placeholder resource. "
                    f"Related context: {context_excerpt[:220]}"
                ),
                query=query,
                provider=FAKE_PROVIDER_NAME,
            )
        )
    return candidates


def _tavily_search(query: str, limit: int, api_key: str) -> List[ResourceCandidate]:
    response = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": limit,
            "search_depth": "basic",
            "include_answer": False,
            "include_images": False,
        },
        timeout=10,
    )
    response.raise_for_status()
    results = response.json().get("results") or []

    candidates = []
    for item in results[:limit]:
        url = item.get("url")
        title = item.get("title")
        if not url or not title:
            continue
        candidates.append(
            ResourceCandidate(
                url=url,
                title=title,
                source_type="article",
                snippet=item.get("content"),
                query=query,
                provider="tavily",
            )
        )
    return candidates


def _brave_search(query: str, limit: int, api_key: str) -> List[ResourceCandidate]:
    response = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": limit},
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        timeout=10,
    )
    response.raise_for_status()
    results = (response.json().get("web") or {}).get("results") or []

    candidates = []
    for item in results[:limit]:
        url = item.get("url")
        title = item.get("title")
        if not url or not title:
            continue
        candidates.append(
            ResourceCandidate(
                url=url,
                title=title,
                source_type="article",
                snippet=item.get("description"),
                query=query,
                provider="brave",
            )
        )
    return candidates


def _get_api_key(provider: str) -> Optional[str]:
    """Return the API key for the given provider.

    For Tavily: checks TAVILY_API_KEY first, then SEARCH_API_KEY (legacy).
    For Brave and others: checks SEARCH_API_KEY only.
    """
    if provider == "tavily":
        return os.environ.get("TAVILY_API_KEY") or os.environ.get("SEARCH_API_KEY")
    return os.environ.get("SEARCH_API_KEY")


def retrieve_resources_for_cluster(
    db: Session, cluster_id: str, limit: int = 5
) -> Optional[List[ResourceCandidate]]:
    """Returns candidate resources for a cluster, or None if the cluster
    doesn't exist. Candidates are NOT validated or stored here — see
    retrieve_and_store_resources_for_cluster for the full pipeline.
    """
    cluster = get_cluster(db, cluster_id)
    if cluster is None:
        return None

    query = generate_cluster_search_query(cluster)
    provider = os.environ.get("SEARCH_PROVIDER")
    api_key = _get_api_key(provider) if provider else None

    if provider in _SUPPORTED_REAL_PROVIDERS and api_key:
        try:
            if provider == "tavily":
                candidates = _tavily_search(query, limit, api_key)
            else:
                candidates = _brave_search(query, limit, api_key)

            if candidates:
                return candidates
            logger.info(
                "resource_retrieval_empty_real_results provider=%s cluster_id=%s",
                provider,
                cluster_id,
            )
        except Exception as exc:
            logger.info(
                "resource_retrieval_real_provider_failed provider=%s cluster_id=%s "
                "failure_type=%s",
                provider,
                cluster_id,
                type(exc).__name__,
            )

    context_excerpt = _context_excerpt_for_fake_provider(cluster)
    return _fake_resources_for_query(query, context_excerpt, limit)


def retrieve_and_store_resources_for_cluster(
    db: Session,
    cluster_id: str,
    limit: int = 5,
    job_id: Optional[str] = None,
) -> Optional[ResourceRetrievalSummary]:
    """Retrieve, validate, and persist accepted resources for a cluster.

    Returns None if the cluster doesn't exist. Rejected candidates are
    discarded, not stored. Candidates whose URL already exists for this
    cluster are validated (and will be flagged as duplicates) but can
    never be inserted twice — the unique(cluster_id, url) constraint is
    the backstop if the in-memory existing_urls check is ever wrong.
    """
    cluster = get_cluster(db, cluster_id)
    if cluster is None:
        return None

    query = generate_cluster_search_query(cluster)
    provider = os.environ.get("SEARCH_PROVIDER") or "unknown"

    start = time.monotonic()
    error_msg: Optional[str] = None
    candidates: List[ResourceCandidate] = []
    try:
        candidates = retrieve_resources_for_cluster(db, cluster_id, limit=limit) or []
        ret_status = "succeeded"
    except Exception as exc:
        ret_status = "failed"
        error_msg = type(exc).__name__
        logger.info(
            "retrieve_and_store_failed cluster_id=%s failure_type=%s",
            cluster_id,
            error_msg,
        )

    latency_ms = int((time.monotonic() - start) * 1000)

    existing_urls = resource_store.get_resource_urls_for_cluster(db, cluster_id)
    accepted_resources: List[Resource] = []
    for candidate in candidates:
        result = validate_resource_for_cluster(cluster, candidate, existing_urls)
        if not result.accepted:
            continue

        resource = Resource(
            cluster_id=cluster_id,
            url=candidate.url,
            title=candidate.title,
            source_type=candidate.source_type,
            snippet=candidate.snippet,
            query=candidate.query,
            relevance_score=result.relevance_score,
            validation_score=result.validation_score,
            validation_reason=result.validation_reason,
            provider=candidate.provider,
        )
        try:
            stored = resource_store.create_resource(db, resource)
        except IntegrityError:
            db.rollback()
            continue
        accepted_resources.append(stored)
        existing_urls.add(candidate.url)

    try:
        if candidates:
            actual_provider = candidates[0].provider if candidates else provider
        else:
            actual_provider = provider
        telemetry.record_retrieval_event(
            db,
            job_id=job_id,
            cluster_id=cluster_id,
            query=query[:500] if query else None,
            provider=actual_provider,
            num_candidates=len(candidates),
            num_accepted=len(accepted_resources),
            latency_ms=latency_ms,
            status=ret_status,
            error=error_msg,
        )
        db.commit()
    except Exception:
        logger.warning("telemetry_retrieval_record_failed", exc_info=True)
        db.rollback()

    if error_msg:
        return ResourceRetrievalSummary(
            resources_retrieved=0,
            resources_accepted=0,
            resources=[],
        )

    return ResourceRetrievalSummary(
        resources_retrieved=len(candidates),
        resources_accepted=len(accepted_resources),
        resources=accepted_resources,
    )
