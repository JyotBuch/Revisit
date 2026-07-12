import json
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.capture import CaptureORM
from app.models.capture_embedding import CaptureEmbeddingORM
from app.models.cluster import ClusterItemORM, ClusterORM
from app.models.job import JobORM
from app.models.resource import ResourceORM
from app.models.revisit_card import RevisitCardORM
from app.models.revisit_card_resource import RevisitCardResourceORM
from app.schemas.capture import CaptureStatus, SourceType
from app.schemas.cluster import ClusterStatus
from app.schemas.job import JobStatus, JobType
from app.schemas.revisit_card import CardType, GenerationMethod
from app.services import feedback_store, telemetry as telemetry_service

EVALS_REPORTS_DIR = Path(__file__).resolve().parents[2] / "evals" / "reports"


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else value


def _get_pipeline_metrics(db: Session) -> Dict[str, Any]:
    total_captures = db.scalar(select(func.count()).select_from(CaptureORM)) or 0

    captures_by_status = {status.value: 0 for status in CaptureStatus}
    for status, count in db.execute(
        select(CaptureORM.status, func.count()).group_by(CaptureORM.status)
    ).all():
        captures_by_status[_enum_value(status)] = count

    captures_by_source_type = {source_type.value: 0 for source_type in SourceType}
    for source_type, count in db.execute(
        select(CaptureORM.source_type, func.count()).group_by(CaptureORM.source_type)
    ).all():
        captures_by_source_type[_enum_value(source_type)] = count

    total_embeddings = db.scalar(select(func.count()).select_from(CaptureEmbeddingORM)) or 0
    total_clusters = db.scalar(select(func.count()).select_from(ClusterORM)) or 0
    total_cluster_items = db.scalar(select(func.count()).select_from(ClusterItemORM)) or 0

    cluster_sizes = (
        select(ClusterItemORM.cluster_id, func.count().label("item_count"))
        .group_by(ClusterItemORM.cluster_id)
        .having(func.count() == 1)
        .subquery()
    )
    singleton_clusters = db.scalar(select(func.count()).select_from(cluster_sizes)) or 0

    average_cluster_size = (
        round(total_cluster_items / total_clusters, 2) if total_clusters > 0 else None
    )

    active_clusters = (
        db.scalar(
            select(func.count())
            .select_from(ClusterORM)
            .where(ClusterORM.status == ClusterStatus.active)
        )
        or 0
    )
    archived_clusters = (
        db.scalar(
            select(func.count())
            .select_from(ClusterORM)
            .where(ClusterORM.status == ClusterStatus.archived)
        )
        or 0
    )

    latest_daily_batch = db.scalar(
        select(JobORM)
        .where(JobORM.job_type == JobType.daily_batch)
        .order_by(JobORM.started_at.desc())
        .limit(1)
    )
    latest_batch_summary = (
        (latest_daily_batch.summary_json or {}) if latest_daily_batch else {}
    )

    return {
        "total_captures": total_captures,
        "captures_by_status": captures_by_status,
        "captures_by_source_type": captures_by_source_type,
        "total_extracted": captures_by_status[CaptureStatus.extracted.value],
        "total_failed_extraction": captures_by_status[CaptureStatus.failed.value],
        "total_embeddings": total_embeddings,
        "total_clusters": total_clusters,
        "total_cluster_items": total_cluster_items,
        "singleton_clusters": singleton_clusters,
        "average_cluster_size": average_cluster_size,
        "active_clusters": active_clusters,
        "archived_clusters": archived_clusters,
        "cluster_reuse_count": latest_batch_summary.get("clusters_reused"),
        "new_clusters_created": latest_batch_summary.get("clusters_created"),
        "archived_clusters_count": latest_batch_summary.get("clusters_archived"),
    }


def _get_revisit_card_metrics(db: Session) -> Dict[str, Any]:
    total_revisit_cards = db.scalar(select(func.count()).select_from(RevisitCardORM)) or 0

    cards_by_type = {card_type.value: 0 for card_type in CardType}
    for card_type, count in db.execute(
        select(RevisitCardORM.card_type, func.count()).group_by(RevisitCardORM.card_type)
    ).all():
        cards_by_type[_enum_value(card_type)] = count

    cards_by_generation_method = {method.value: 0 for method in GenerationMethod}
    for method, count in db.execute(
        select(RevisitCardORM.generation_method, func.count()).group_by(
            RevisitCardORM.generation_method
        )
    ).all():
        cards_by_generation_method[_enum_value(method)] = count

    return {
        "total_revisit_cards": total_revisit_cards,
        "cards_by_type": cards_by_type,
        "cards_by_generation_method": cards_by_generation_method,
        "llm_card_count": cards_by_generation_method[GenerationMethod.llm.value],
        "rule_based_card_count": cards_by_generation_method[
            GenerationMethod.rule_based.value
        ],
    }


def _get_feedback_metrics(db: Session) -> Dict[str, Any]:
    summary = feedback_store.summarize_feedback(db)
    total = summary["total_feedback_events"]
    next_action_taken_count = summary["counts_by_action"].get("next_action_taken", 0)
    next_action_taken_rate = next_action_taken_count / total if total > 0 else None

    return {
        "total_feedback_events": total,
        "feedback_counts_by_action": summary["counts_by_action"],
        "average_rating": summary["average_rating"],
        "useful_rate": summary["useful_rate"],
        "dismiss_rate": summary["dismiss_rate"],
        "next_action_taken_rate": next_action_taken_rate,
    }


def _get_eval_metrics() -> Dict[str, Any]:
    metrics: Dict[str, Any] = {
        "latest_eval_report_path": None,
        "latest_eval_timestamp": None,
        "latest_rule_based_pass_rate": None,
        "latest_llm_pass_rate": None,
    }

    if not EVALS_REPORTS_DIR.is_dir():
        return metrics

    report_files = sorted(
        EVALS_REPORTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime
    )
    if not report_files:
        return metrics

    latest = report_files[-1]
    metrics["latest_eval_report_path"] = str(latest)

    try:
        data = json.loads(latest.read_text())
    except (json.JSONDecodeError, OSError):
        return metrics

    metrics["latest_eval_timestamp"] = data.get("eval_timestamp")

    summary = data.get("summary") or {}
    rule_based = summary.get("rule_based") or {}
    llm_summary = summary.get("llm") or {}
    metrics["latest_rule_based_pass_rate"] = rule_based.get("pass_rate")
    metrics["latest_llm_pass_rate"] = llm_summary.get("pass_rate")

    return metrics


def _get_job_metrics(db: Session) -> Dict[str, Any]:
    total_jobs = db.scalar(select(func.count()).select_from(JobORM)) or 0

    jobs_by_status = {status.value: 0 for status in JobStatus}
    for status, count in db.execute(
        select(JobORM.status, func.count()).group_by(JobORM.status)
    ).all():
        jobs_by_status[_enum_value(status)] = count

    latest_daily_batch = db.scalar(
        select(JobORM)
        .where(JobORM.job_type == JobType.daily_batch)
        .order_by(JobORM.started_at.desc())
        .limit(1)
    )

    return {
        "total_jobs": total_jobs,
        "jobs_by_status": jobs_by_status,
        "latest_daily_batch_status": (
            _enum_value(latest_daily_batch.status) if latest_daily_batch else None
        ),
        "latest_daily_batch_started_at": (
            latest_daily_batch.started_at.isoformat() if latest_daily_batch else None
        ),
        "latest_daily_batch_completed_at": (
            latest_daily_batch.completed_at.isoformat()
            if latest_daily_batch and latest_daily_batch.completed_at
            else None
        ),
    }


def _get_resource_metrics(db: Session) -> Dict[str, Any]:
    total_resources = db.scalar(select(func.count()).select_from(ResourceORM)) or 0

    resources_by_provider: Dict[str, int] = {}
    for provider, count in db.execute(
        select(ResourceORM.provider, func.count()).group_by(ResourceORM.provider)
    ).all():
        resources_by_provider[provider or "unknown"] = count

    average_validation_score = db.scalar(
        select(func.avg(ResourceORM.validation_score)).where(
            ResourceORM.validation_score.is_not(None)
        )
    )
    if average_validation_score is not None:
        average_validation_score = round(float(average_validation_score), 3)

    clusters_with_resources = (
        db.scalar(select(func.count(func.distinct(ResourceORM.cluster_id)))) or 0
    )

    total_card_resource_links = (
        db.scalar(select(func.count()).select_from(RevisitCardResourceORM)) or 0
    )
    cards_with_resources = (
        db.scalar(
            select(func.count(func.distinct(RevisitCardResourceORM.revisit_card_id)))
        )
        or 0
    )
    average_resources_per_resource_aware_card = (
        round(total_card_resource_links / cards_with_resources, 2)
        if cards_with_resources > 0
        else None
    )

    return {
        "total_resources": total_resources,
        "resources_by_provider": resources_by_provider,
        "average_resource_validation_score": average_validation_score,
        "clusters_with_resources": clusters_with_resources,
        "total_card_resource_links": total_card_resource_links,
        "cards_with_resources": cards_with_resources,
        "average_resources_per_resource_aware_card": average_resources_per_resource_aware_card,
    }


def _get_telemetry_metrics(db: Session) -> Dict[str, Any]:
    summary = telemetry_service.get_telemetry_summary(db)
    return {
        "total_llm_calls": summary["total_llm_calls"],
        "total_tokens": summary["total_tokens"],
        "estimated_cost_usd": summary["estimated_cost_usd"],
        "average_llm_latency_ms": summary["average_llm_latency_ms"],
        "failed_agent_steps": summary["failed_agent_steps"],
        "retrieval_events": summary["retrieval_events"],
        "average_retrieval_latency_ms": summary["average_retrieval_latency_ms"],
    }


def get_observability_metrics(db: Session) -> Dict[str, Any]:
    return {
        "pipeline": _get_pipeline_metrics(db),
        "revisit_cards": _get_revisit_card_metrics(db),
        "feedback": _get_feedback_metrics(db),
        "eval": _get_eval_metrics(),
        "jobs": _get_job_metrics(db),
        "resources": _get_resource_metrics(db),
        "telemetry": _get_telemetry_metrics(db),
    }
