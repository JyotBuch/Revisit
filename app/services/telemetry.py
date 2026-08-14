"""Telemetry service — persists LLM call records, agent steps, and retrieval
events. All writes are best-effort: callers should not let a telemetry failure
surface to end users.

Privacy invariant: raw prompt text and raw capture/user content are never
stored here. Only ids, counts, status, model names, and latency metrics.
"""

import hashlib
import hmac
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.telemetry import AgentStepORM, LlmCallORM, RetrievalEventORM, TelemetryDailyAggregateORM

# Prices in USD per token — last updated 2026-07 against OpenAI published rates.
# (input_usd_per_token, output_usd_per_token)
_COST_TABLE: dict[str, tuple[float, float]] = {
    "gpt-4o":                 (2.50e-6, 10.00e-6),
    "gpt-4o-mini":            (0.15e-6,  0.60e-6),
    "gpt-4-turbo":            (10.00e-6, 30.00e-6),
    "gpt-3.5-turbo":          (0.50e-6,  1.50e-6),
    "text-embedding-3-small": (0.02e-6,  0.0),
    "text-embedding-3-large": (0.13e-6,  0.0),
    "text-embedding-ada-002": (0.10e-6,  0.0),
}

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization|api[_-]?key|access[_-]?token|password)\s*[:=]\s*\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?i)(https?://[^\s?]+)\?\S+"),
    re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:eyJ[A-Za-z0-9_-]+\.){2}[A-Za-z0-9_-]+\b"),
]


def enabled() -> bool:
    return os.environ.get("AGENT_TELEMETRY_ENABLED", "true").lower() == "true"


def _expiry() -> datetime:
    days = max(1, int(os.environ.get("TELEMETRY_RETENTION_DAYS", "30")))
    return datetime.now(timezone.utc) + timedelta(days=days)


def content_hash(value: str | None) -> str | None:
    if not value:
        return None
    secret = os.environ.get("TELEMETRY_HASH_SECRET") or os.environ.get("GOOGLE_WEB_CLIENT_SECRET") or "local-telemetry"
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def redact(
    value: str | None, limit: int = 500,
    sensitive_values: list[str | None] | None = None,
) -> str | None:
    if not value:
        return None
    cleaned = value
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[REDACTED]", cleaned)
    # Remove exact user-provided passages/notes if a model echoes them. Very
    # short strings are skipped to avoid destroying ordinary prose.
    for sensitive in sensitive_values or []:
        if sensitive and len(sensitive.strip()) >= 12:
            cleaned = cleaned.replace(sensitive.strip(), "[USER_CONTENT_REDACTED]")
    return cleaned[:limit]


def _safe_summary(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k)[:80]: _safe_summary(v) for k, v in value.items() if str(k).lower() not in {"prompt", "content", "capture", "note", "query"}}
    if isinstance(value, list):
        return [_safe_summary(v) for v in value[:50]]
    if isinstance(value, str):
        return redact(value, 200)
    return value


def estimate_cost(model_name: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    pricing = _COST_TABLE.get(model_name)
    if pricing is None:
        for key, val in _COST_TABLE.items():
            if model_name.startswith(key):
                pricing = val
                break
    if pricing is None:
        return None
    in_price, out_price = pricing
    return round(input_tokens * in_price + output_tokens * out_price, 8)


# ---------------------------------------------------------------------------
# Agent steps
# ---------------------------------------------------------------------------

def start_agent_step(
    db: Session,
    *,
    job_id: Optional[str] = None,
    step_name: str,
    owner_type: Optional[str] = None,
    owner_id: Optional[str] = None,
    input_summary: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
) -> AgentStepORM:
    now = datetime.now(timezone.utc)
    row = AgentStepORM(
        id=str(uuid.uuid4()),
        user_id=user_id,
        job_id=job_id,
        step_name=step_name,
        owner_type=owner_type,
        owner_id=owner_id,
        status="started",
        started_at=now,
        input_summary_json=_safe_summary(input_summary),
        expires_at=_expiry(),
    )
    db.add(row)
    db.flush()
    return row


def complete_agent_step(
    db: Session,
    step_id: str,
    output_summary: Optional[Dict[str, Any]] = None,
) -> None:
    row = db.get(AgentStepORM, step_id)
    if row is None:
        return
    now = datetime.now(timezone.utc)
    row.status = "succeeded"
    row.completed_at = now
    row.output_summary_json = _safe_summary(output_summary)
    elapsed = (now - row.started_at).total_seconds()
    row.latency_ms = int(elapsed * 1000)
    db.flush()


def fail_agent_step(db: Session, step_id: str, error: str) -> None:
    row = db.get(AgentStepORM, step_id)
    if row is None:
        return
    now = datetime.now(timezone.utc)
    row.status = "failed"
    row.completed_at = now
    row.error = redact(error, 2000)
    elapsed = (now - row.started_at).total_seconds()
    row.latency_ms = int(elapsed * 1000)
    db.flush()


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------

def record_llm_call(
    db: Session,
    *,
    job_id: Optional[str] = None,
    owner_type: Optional[str] = None,
    owner_id: Optional[str] = None,
    purpose: str,
    model_name: str,
    prompt_version: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    latency_ms: Optional[int] = None,
    status: str,
    failure_type: Optional[str] = None,
    user_id: Optional[str] = None,
    provider_request_id: Optional[str] = None,
    finish_reason: Optional[str] = None,
    request_content: Optional[str] = None,
    response_content: Optional[str] = None,
    sensitive_values: Optional[list[str | None]] = None,
) -> LlmCallORM:
    cost: Optional[float] = None
    if input_tokens is not None and output_tokens is not None:
        cost = estimate_cost(model_name, input_tokens, output_tokens)

    row = LlmCallORM(
        id=str(uuid.uuid4()),
        user_id=user_id,
        job_id=job_id,
        owner_type=owner_type,
        owner_id=owner_id,
        purpose=purpose,
        model_name=model_name,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=cost,
        latency_ms=latency_ms,
        status=status,
        failure_type=failure_type,
        provider_request_id=provider_request_id,
        finish_reason=finish_reason,
        request_hash=content_hash(request_content),
        response_hash=content_hash(response_content),
        response_excerpt=redact(response_content, sensitive_values=sensitive_values),
        expires_at=_expiry(),
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Retrieval events
# ---------------------------------------------------------------------------

def record_retrieval_event(
    db: Session,
    *,
    job_id: Optional[str] = None,
    cluster_id: Optional[str] = None,
    query: Optional[str] = None,
    provider: Optional[str] = None,
    num_candidates: Optional[int] = None,
    num_accepted: Optional[int] = None,
    latency_ms: Optional[int] = None,
    status: str,
    error: Optional[str] = None,
    user_id: Optional[str] = None,
    owner_type: Optional[str] = None,
    owner_id: Optional[str] = None,
    query_intent: Optional[str] = None,
    accepted_ids: Optional[list[str]] = None,
    memory_ids: Optional[list[str]] = None,
    memory_scores: Optional[list[float]] = None,
) -> RetrievalEventORM:
    row = RetrievalEventORM(
        id=str(uuid.uuid4()),
        user_id=user_id,
        job_id=job_id,
        cluster_id=cluster_id,
        owner_type=owner_type,
        owner_id=owner_id,
        query=None,
        query_hash=content_hash(query),
        query_intent=redact(query_intent, 120),
        provider=provider,
        num_candidates=num_candidates,
        num_accepted=num_accepted,
        latency_ms=latency_ms,
        status=status,
        error=redact(error, 1000),
        accepted_ids_json=(accepted_ids or [])[:50],
        memory_ids_json=(memory_ids or [])[:20],
        memory_scores_json=(memory_scores or [])[:20],
        expires_at=_expiry(),
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def _step_dict(row: AgentStepORM) -> Dict[str, Any]:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "step_name": row.step_name,
        "owner_type": row.owner_type,
        "owner_id": row.owner_id,
        "status": row.status,
        "started_at": row.started_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "latency_ms": row.latency_ms,
        "input_summary_json": row.input_summary_json,
        "output_summary_json": row.output_summary_json,
        "error": row.error,
    }


def _llm_call_dict(row: LlmCallORM) -> Dict[str, Any]:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "owner_type": row.owner_type,
        "owner_id": row.owner_id,
        "purpose": row.purpose,
        "model_name": row.model_name,
        "prompt_version": row.prompt_version,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "total_tokens": row.total_tokens,
        "estimated_cost_usd": row.estimated_cost_usd,
        "latency_ms": row.latency_ms,
        "status": row.status,
        "failure_type": row.failure_type,
        "provider_request_id": row.provider_request_id,
        "finish_reason": row.finish_reason,
        "request_hash": row.request_hash,
        "response_hash": row.response_hash,
        "response_excerpt": row.response_excerpt,
        "created_at": row.created_at.isoformat(),
    }


def _retrieval_event_dict(row: RetrievalEventORM) -> Dict[str, Any]:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "cluster_id": row.cluster_id,
        "query_hash": row.query_hash,
        "query_intent": row.query_intent,
        "provider": row.provider,
        "num_candidates": row.num_candidates,
        "num_accepted": row.num_accepted,
        "latency_ms": row.latency_ms,
        "status": row.status,
        "error": row.error,
        "accepted_ids": row.accepted_ids_json,
        "memory_ids": row.memory_ids_json,
        "memory_scores": row.memory_scores_json,
        "created_at": row.created_at.isoformat(),
    }


def get_job_trace(db: Session, job_id: str) -> Dict[str, Any]:
    steps = db.scalars(
        select(AgentStepORM)
        .where(AgentStepORM.job_id == job_id)
        .order_by(AgentStepORM.started_at)
    ).all()

    llm_calls = db.scalars(
        select(LlmCallORM)
        .where(LlmCallORM.job_id == job_id)
        .order_by(LlmCallORM.created_at)
    ).all()

    retrieval_events = db.scalars(
        select(RetrievalEventORM)
        .where(RetrievalEventORM.job_id == job_id)
        .order_by(RetrievalEventORM.created_at)
    ).all()

    total_tokens = sum(c.total_tokens or 0 for c in llm_calls)
    total_cost = sum(c.estimated_cost_usd or 0.0 for c in llm_calls)

    return {
        "job_id": job_id,
        "agent_steps": [_step_dict(s) for s in steps],
        "llm_calls": [_llm_call_dict(c) for c in llm_calls],
        "retrieval_events": [_retrieval_event_dict(e) for e in retrieval_events],
        "aggregate": {
            "total_tokens": total_tokens,
            "estimated_cost_usd": round(total_cost, 6),
            "llm_call_count": len(llm_calls),
            "agent_step_count": len(steps),
            "retrieval_event_count": len(retrieval_events),
        },
    }


def get_telemetry_summary(db: Session) -> Dict[str, Any]:
    rollups = db.scalars(select(TelemetryDailyAggregateORM)).all()
    rolled = [row.metrics_json or {} for row in rollups]
    rolled_calls = int(sum(float(item.get("llm_calls", 0)) for item in rolled))
    rolled_failed_calls = int(sum(float(item.get("failed_llm_calls", 0)) for item in rolled))
    total_llm_calls = db.scalar(select(func.count()).select_from(LlmCallORM)) or 0

    llm_calls_by_status: Dict[str, int] = {}
    for status, count in db.execute(
        select(LlmCallORM.status, func.count()).group_by(LlmCallORM.status)
    ).all():
        llm_calls_by_status[status] = count
    if rolled_calls:
        llm_calls_by_status["succeeded"] = llm_calls_by_status.get("succeeded", 0) + rolled_calls - rolled_failed_calls
        llm_calls_by_status["failed"] = llm_calls_by_status.get("failed", 0) + rolled_failed_calls

    total_tokens = int(
        db.scalar(select(func.sum(LlmCallORM.total_tokens))) or 0
    ) + int(sum(float(item.get("tokens", 0)) for item in rolled))

    tokens_by_model: Dict[str, int] = {}
    for model, tok in db.execute(
        select(LlmCallORM.model_name, func.sum(LlmCallORM.total_tokens))
        .group_by(LlmCallORM.model_name)
    ).all():
        tokens_by_model[model] = int(tok or 0)
    for item in rolled:
        for key, value in item.items():
            if key.startswith("tokens_model__"):
                model = key.removeprefix("tokens_model__")
                tokens_by_model[model] = tokens_by_model.get(model, 0) + int(float(value))

    raw_cost = db.scalar(select(func.sum(LlmCallORM.estimated_cost_usd)))
    rolled_cost = sum(float(item.get("cost_usd", 0)) for item in rolled)
    estimated_cost_usd = (
        round(float(raw_cost or 0) + rolled_cost, 6)
        if raw_cost is not None or rolled_calls else None
    )

    live_successes = int(db.scalar(select(func.count()).select_from(LlmCallORM).where(LlmCallORM.status == "succeeded")) or 0)
    live_latency_sum = float(db.scalar(select(func.sum(LlmCallORM.latency_ms)).where(LlmCallORM.status == "succeeded")) or 0)
    rolled_successes = rolled_calls - rolled_failed_calls
    latency_denominator = live_successes + rolled_successes
    average_llm_latency_ms = round(
        (live_latency_sum + sum(float(item.get("llm_latency_ms", 0)) for item in rolled)) / latency_denominator, 1,
    ) if latency_denominator else None

    failed_agent_steps = (
        db.scalar(
            select(func.count())
            .select_from(AgentStepORM)
            .where(AgentStepORM.status == "failed")
        )
        or 0
    ) + int(sum(float(item.get("failed_steps", 0)) for item in rolled))

    retrieval_events = (
        db.scalar(select(func.count()).select_from(RetrievalEventORM)) or 0
    ) + int(sum(float(item.get("retrieval_events", 0)) for item in rolled))

    live_retrieval_successes = int(db.scalar(select(func.count()).select_from(RetrievalEventORM).where(RetrievalEventORM.status == "succeeded")) or 0)
    live_retrieval_latency = float(db.scalar(select(func.sum(RetrievalEventORM.latency_ms)).where(RetrievalEventORM.status == "succeeded")) or 0)
    rolled_retrieval_successes = int(sum(float(item.get("successful_retrieval_events", 0)) for item in rolled))
    retrieval_latency_denominator = live_retrieval_successes + rolled_retrieval_successes
    average_retrieval_latency_ms = round(
        (live_retrieval_latency + sum(float(item.get("retrieval_latency_ms", 0)) for item in rolled)) / retrieval_latency_denominator, 1,
    ) if retrieval_latency_denominator else None

    return {
        "total_llm_calls": total_llm_calls + rolled_calls,
        "llm_calls_by_status": llm_calls_by_status,
        "total_tokens": total_tokens,
        "tokens_by_model": tokens_by_model,
        "estimated_cost_usd": estimated_cost_usd,
        "average_llm_latency_ms": average_llm_latency_ms,
        "failed_agent_steps": failed_agent_steps,
        "retrieval_events": retrieval_events,
        "average_retrieval_latency_ms": average_retrieval_latency_ms,
    }


def purge_expired(db: Session) -> int:
    now = datetime.now(timezone.utc)
    aggregates: dict[Any, dict[str, float]] = {}
    calls = db.execute(
        delete(LlmCallORM)
        .where(LlmCallORM.expires_at.is_not(None), LlmCallORM.expires_at < now)
        .returning(
            LlmCallORM.created_at,
            LlmCallORM.status,
            LlmCallORM.total_tokens,
            LlmCallORM.estimated_cost_usd,
            LlmCallORM.latency_ms,
            LlmCallORM.model_name,
        )
    ).all()
    for created_at, status, total_tokens, estimated_cost_usd, latency_ms, model_name in calls:
        day = created_at.astimezone(timezone.utc).date()
        bucket = aggregates.setdefault(day, {"llm_calls": 0, "failed_llm_calls": 0, "tokens": 0, "cost_usd": 0.0, "llm_latency_ms": 0, "retrieval_events": 0, "successful_retrieval_events": 0, "retrieval_latency_ms": 0, "failed_steps": 0})
        bucket["llm_calls"] += 1
        bucket["failed_llm_calls"] += int(status != "succeeded")
        bucket["tokens"] += total_tokens or 0
        model_key = "tokens_model__" + (redact(model_name, 80) or "unknown")
        bucket[model_key] = bucket.get(model_key, 0) + (total_tokens or 0)
        bucket["cost_usd"] += estimated_cost_usd or 0.0
        bucket["llm_latency_ms"] += latency_ms or 0
    retrievals = db.execute(
        delete(RetrievalEventORM)
        .where(RetrievalEventORM.expires_at.is_not(None), RetrievalEventORM.expires_at < now)
        .returning(RetrievalEventORM.created_at, RetrievalEventORM.status, RetrievalEventORM.latency_ms)
    ).all()
    for created_at, status, latency_ms in retrievals:
        day = created_at.astimezone(timezone.utc).date()
        bucket = aggregates.setdefault(day, {"llm_calls": 0, "failed_llm_calls": 0, "tokens": 0, "cost_usd": 0.0, "llm_latency_ms": 0, "retrieval_events": 0, "successful_retrieval_events": 0, "retrieval_latency_ms": 0, "failed_steps": 0})
        bucket["retrieval_events"] += 1
        if status == "succeeded":
            bucket["successful_retrieval_events"] += 1
            bucket["retrieval_latency_ms"] += latency_ms or 0
    steps = db.execute(
        delete(AgentStepORM)
        .where(AgentStepORM.expires_at.is_not(None), AgentStepORM.expires_at < now)
        .returning(AgentStepORM.started_at, AgentStepORM.status)
    ).all()
    for started_at, status in steps:
        day = started_at.astimezone(timezone.utc).date()
        bucket = aggregates.setdefault(day, {"llm_calls": 0, "failed_llm_calls": 0, "tokens": 0, "cost_usd": 0.0, "llm_latency_ms": 0, "retrieval_events": 0, "successful_retrieval_events": 0, "retrieval_latency_ms": 0, "failed_steps": 0})
        bucket["failed_steps"] += int(status == "failed")
    for day, values in aggregates.items():
        aggregate = db.get(TelemetryDailyAggregateORM, day)
        if aggregate is None:
            aggregate = TelemetryDailyAggregateORM(day=day, metrics_json=values)
            db.add(aggregate)
        else:
            aggregate.metrics_json = {
                key: round(float((aggregate.metrics_json or {}).get(key, 0)) + float(value), 8)
                for key, value in values.items()
            }
    db.commit()
    return len(calls) + len(retrievals) + len(steps)
