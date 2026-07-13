import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cluster import ClusterORM
from app.models.revisit_card import RevisitCardORM
from app.schemas.capture import Capture, CaptureLabel, SourceType
from app.schemas.resource import Resource
from app.schemas.revisit_card import CardType, GenerationMethod, RevisitCard
from app.services import llm, resource_store

logger = logging.getLogger("revisit.revisit_cards")

_NEXT_ACTION_BY_SOURCE_TYPE = {
    SourceType.article: (
        "Review the saved text and write down the main question you want to answer."
    ),
    SourceType.passage: (
        "Review the saved text and write down the main question you want to answer."
    ),
    SourceType.video: (
        "Watch or rewatch the saved video and note the key idea to follow up on."
    ),
    SourceType.image: (
        "Review the saved image and describe what detail is worth coming back to."
    ),
    SourceType.note: "Expand this note into one concrete follow-up task.",
}

_CLUSTER_NEXT_ACTION_BY_SOURCE_TYPE = {
    SourceType.article: (
        "Review the saved text and write down the main question this thread should answer."
    ),
    SourceType.passage: (
        "Review the saved text and write down the main question this thread should answer."
    ),
    SourceType.video: (
        "Watch the saved videos and note the recurring idea to follow up on."
    ),
    SourceType.image: (
        "Review the saved images and describe the detail worth returning to."
    ),
    SourceType.note: "Expand these notes into one concrete follow-up task.",
}

_CLUSTER_MIXED_SOURCE_NEXT_ACTION = (
    "Review the grouped captures and identify the main question connecting them."
)

_MAX_CLUSTER_CONTEXT_SNIPPETS = 3
_MAX_SNIPPET_LENGTH = 200
_MAX_LLM_CONTEXT_CAPTURES = 5
_MAX_RESOURCES_PER_CARD = 5


def _log_fallback(owner_type: str, owner_id: str) -> None:
    logger.info("rule_based_fallback_used owner_type=%s owner_id=%s", owner_type, owner_id)


def _build_title(capture: Capture) -> str:
    return capture.title or "Untitled Revisit Card"


def _build_why_saved(capture: Capture) -> str:
    if capture.label == CaptureLabel.return_:
        return "You marked this capture as worth returning to."
    return "You saved this capture casually."


def _build_original_context(capture: Capture) -> Optional[str]:
    return capture.user_note or capture.selected_text or capture.url


def _build_next_action(capture: Capture) -> str:
    return _NEXT_ACTION_BY_SOURCE_TYPE[capture.source_type]


_MAX_EXTRACTED_TEXT_FOR_LLM = 4000


def _capture_context_item(capture: Capture) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "source_type": capture.source_type.value,
        "label": capture.label.value,
        "title": capture.title,
        "url": capture.url,
    }
    if capture.user_note:
        item["user_note"] = capture.user_note
    if capture.selected_text:
        item["selected_text"] = capture.selected_text
    if capture.extracted_text:
        text = capture.extracted_text
        item["extracted_text"] = (
            text[:_MAX_EXTRACTED_TEXT_FOR_LLM] + "…"
            if len(text) > _MAX_EXTRACTED_TEXT_FOR_LLM
            else text
        )
    return item


def create_revisit_card_for_capture(
    db: Session,
    capture: Capture,
    generation_method: GenerationMethod = GenerationMethod.rule_based,
    job_id: Optional[str] = None,
) -> RevisitCard:
    actual_method = GenerationMethod.rule_based
    model_name = None
    prompt_version = None

    title = why_saved = original_context = next_action = None

    if generation_method == GenerationMethod.llm:
        context = {"card_kind": "individual", "captures": [_capture_context_item(capture)]}
        result = llm.generate_revisit_card_content(
            context, owner_type="capture", owner_id=capture.id, db=db, job_id=job_id
        )
        if result is not None:
            title = result["title"]
            why_saved = result["why_saved"]
            original_context = result["original_context"]
            next_action = result["next_action"]
            actual_method = GenerationMethod.llm
            model_name = llm.get_active_model_name()
            prompt_version = llm.PROMPT_VERSION
        else:
            _log_fallback("capture", capture.id)

    if actual_method == GenerationMethod.rule_based:
        title = _build_title(capture)
        why_saved = _build_why_saved(capture)
        original_context = _build_original_context(capture)
        next_action = _build_next_action(capture)

    row = RevisitCardORM(
        id=str(uuid.uuid4()),
        capture_id=capture.id,
        card_type=CardType.individual,
        generation_method=actual_method,
        model_name=model_name,
        prompt_version=prompt_version,
        title=title,
        why_saved=why_saved,
        original_context=original_context,
        next_action=next_action,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return RevisitCard.model_validate(row, from_attributes=True)


def _build_cluster_title(cluster: ClusterORM, captures: List[Capture]) -> str:
    if cluster.title:
        return cluster.title
    if captures and captures[0].title:
        return captures[0].title
    return "Untitled Revisit Card"


def _build_cluster_why_saved(captures: List[Capture]) -> str:
    if any(c.label == CaptureLabel.return_ for c in captures):
        return "You saved multiple related captures as worth returning to."
    return "You saved multiple related captures casually."


def _capture_snippet(capture: Capture) -> Optional[str]:
    text = capture.user_note or capture.selected_text or capture.extracted_text or capture.url
    if not text:
        return None
    text = text.strip()
    if len(text) > _MAX_SNIPPET_LENGTH:
        text = text[:_MAX_SNIPPET_LENGTH].rstrip() + "..."
    return text


def _build_cluster_original_context(captures: List[Capture]) -> Optional[str]:
    snippets = []
    for capture in captures:
        snippet = _capture_snippet(capture)
        if snippet:
            snippets.append(snippet)
        if len(snippets) == _MAX_CLUSTER_CONTEXT_SNIPPETS:
            break
    if not snippets:
        return None
    return "\n\n".join(f"- {snippet}" for snippet in snippets)


def _build_cluster_next_action(captures: List[Capture]) -> str:
    source_types = {c.source_type for c in captures}
    if len(source_types) > 1:
        return _CLUSTER_MIXED_SOURCE_NEXT_ACTION
    only_type = next(iter(source_types))
    return _CLUSTER_NEXT_ACTION_BY_SOURCE_TYPE[only_type]


def _top_resources_for_cluster(db: Session, cluster_id: str) -> List[Resource]:
    """Top accepted resources for a cluster, by validation_score, capped.

    Every row in `resources` has already passed validate_resource_for_cluster
    before being stored (see retrieval.py), so no further filtering is
    needed here beyond ranking and capping.
    """
    all_resources = resource_store.list_resources_for_cluster(db, cluster_id)
    return sorted(
        all_resources, key=lambda r: r.validation_score or 0.0, reverse=True
    )[:_MAX_RESOURCES_PER_CARD]


def _resource_context_item(resource: Resource) -> Dict[str, Any]:
    return {
        "title": resource.title,
        "url": resource.url,
        "snippet": resource.snippet,
        "validation_score": resource.validation_score,
    }


def _build_resource_section(resources: List[Resource]) -> Optional[str]:
    """Concise, factual listing of resource titles only — never invents
    descriptions beyond what's already stored (title/snippet/url)."""
    if not resources:
        return None
    lines = "\n".join(f"- {resource.title}" for resource in resources)
    return f"Related resources prepared:\n{lines}"


def create_revisit_card_for_cluster(
    db: Session,
    cluster: ClusterORM,
    generation_method: GenerationMethod = GenerationMethod.rule_based,
    include_resources: bool = True,
    job_id: Optional[str] = None,
) -> RevisitCard:
    captures = [
        Capture.model_validate(item.capture, from_attributes=True)
        for item in cluster.items
    ]

    top_resources: List[Resource] = (
        _top_resources_for_cluster(db, cluster.id) if include_resources else []
    )

    actual_method = GenerationMethod.rule_based
    model_name = None
    prompt_version = None
    title = why_saved = original_context = next_action = None

    if generation_method == GenerationMethod.llm:
        context = {
            "card_kind": "cluster",
            "cluster_title": cluster.title,
            "captures": [
                _capture_context_item(c) for c in captures[:_MAX_LLM_CONTEXT_CAPTURES]
            ],
        }
        if top_resources:
            context["resources"] = [_resource_context_item(r) for r in top_resources]
        result = llm.generate_revisit_card_content(
            context, owner_type="cluster", owner_id=cluster.id, db=db, job_id=job_id
        )
        if result is not None:
            title = result["title"]
            why_saved = result["why_saved"]
            original_context = result["original_context"]
            next_action = result["next_action"]
            actual_method = GenerationMethod.llm
            model_name = llm.get_active_model_name()
            prompt_version = llm.PROMPT_VERSION
        else:
            _log_fallback("cluster", cluster.id)

    if actual_method == GenerationMethod.rule_based:
        title = _build_cluster_title(cluster, captures)
        why_saved = _build_cluster_why_saved(captures)
        original_context = _build_cluster_original_context(captures)
        next_action = _build_cluster_next_action(captures)
        resource_section = _build_resource_section(top_resources)
        if resource_section:
            original_context = (
                f"{original_context}\n\n{resource_section}"
                if original_context
                else resource_section
            )

    row = RevisitCardORM(
        id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        card_type=CardType.cluster,
        generation_method=actual_method,
        model_name=model_name,
        prompt_version=prompt_version,
        title=title,
        why_saved=why_saved,
        original_context=original_context,
        next_action=next_action,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    for resource in top_resources:
        resource_store.link_resource_to_card(db, row.id, resource.id)

    return RevisitCard.model_validate(row, from_attributes=True)


def get_latest_card_for_cluster(db: Session, cluster_id: str) -> Optional[RevisitCard]:
    row = db.scalar(
        select(RevisitCardORM)
        .where(RevisitCardORM.cluster_id == cluster_id)
        .order_by(RevisitCardORM.created_at.desc())
        .limit(1)
    )
    if row is None:
        return None
    return RevisitCard.model_validate(row, from_attributes=True)


def list_revisit_cards(db: Session) -> List[RevisitCard]:
    rows = db.scalars(select(RevisitCardORM)).all()
    return [RevisitCard.model_validate(row, from_attributes=True) for row in rows]


def get_revisit_card(db: Session, card_id: str) -> Optional[RevisitCard]:
    row = db.get(RevisitCardORM, card_id)
    if row is None:
        return None
    return RevisitCard.model_validate(row, from_attributes=True)
