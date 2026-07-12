"""Deterministic resource validation — lightweight, lexical-overlap based.

Kept deterministic (not LLM-judged) for the same reason extraction's and
clustering's first passes were deterministic: a cheap, inspectable,
explainable check lets the retrieve -> validate -> store loop be built and
exercised end-to-end before adding a more expensive/judgment-based layer
on top. An LLM-as-judge for resource relevance is a plausible later
upgrade once this proves the pipeline shape works, not a starting point.
"""

import re
from dataclasses import dataclass
from typing import Optional, Set

from app.models.cluster import ClusterORM
from app.schemas.resource import ResourceCandidate

DEFAULT_VALIDATION_THRESHOLD = 0.50

_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is",
    "are", "with", "this", "that", "it", "be", "as", "at", "by", "from",
    "your", "you", "more", "about",
}


@dataclass
class ResourceValidationResult:
    relevance_score: float
    validation_score: float
    validation_reason: str
    accepted: bool


def _tokenize(text: Optional[str]) -> Set[str]:
    if not text:
        return set()
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _cluster_context_tokens(cluster: ClusterORM) -> Set[str]:
    tokens = _tokenize(cluster.title)
    for item in cluster.items:
        capture = item.capture
        tokens |= _tokenize(capture.title)
        tokens |= _tokenize(capture.user_note)
        tokens |= _tokenize(capture.selected_text)
        tokens |= _tokenize(capture.extracted_text)
    return tokens


def _lexical_overlap(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def validate_resource_for_cluster(
    cluster: ClusterORM,
    resource_candidate: ResourceCandidate,
    existing_urls: Set[str],
    threshold: float = DEFAULT_VALIDATION_THRESHOLD,
) -> ResourceValidationResult:
    reasons = []

    has_url = bool(resource_candidate.url and resource_candidate.url.strip())
    has_title = bool(resource_candidate.title and resource_candidate.title.strip())
    is_duplicate = resource_candidate.url in existing_urls

    if not has_url:
        reasons.append("missing url")
    if not has_title:
        reasons.append("missing title")
    if is_duplicate:
        reasons.append("duplicate url for this cluster")

    context_tokens = _cluster_context_tokens(cluster)
    resource_tokens = (
        _tokenize(resource_candidate.title)
        | _tokenize(resource_candidate.snippet)
        | _tokenize(resource_candidate.query)
    )
    relevance_score = round(_lexical_overlap(context_tokens, resource_tokens), 3)

    if reasons:
        validation_score = 0.0
    else:
        validation_score = relevance_score

    accepted = not reasons and validation_score >= threshold

    if accepted:
        reason_text = (
            f"accepted: relevance_score={relevance_score} >= threshold {threshold}, "
            "url/title present, not a duplicate"
        )
    elif reasons:
        reason_text = f"rejected: {', '.join(reasons)}"
    else:
        reason_text = (
            f"rejected: relevance_score={relevance_score} below threshold {threshold}"
        )

    return ResourceValidationResult(
        relevance_score=relevance_score,
        validation_score=validation_score,
        validation_reason=reason_text,
        accepted=accepted,
    )
