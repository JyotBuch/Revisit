"""Telemetry service — persists LLM call records, agent steps, and retrieval
events. All writes are best-effort: callers should not let a telemetry failure
surface to end users.

Privacy invariant: raw prompt text and raw capture/user content are never
stored here. Only ids, counts, status, model names, and latency metrics.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.telemetry import AgentStepORM, LlmCallORM, RetrievalEventORM

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
) -> AgentStepORM:
    now = datetime.now(timezone.utc)
    row = AgentStepORM(
        id=str(uuid.uuid4()),
        job_id=job_id,
        step_name=step_name,
        owner_type=owner_type,
        owner_id=owner_id,
        status="started",
        started_at=now,
        input_summary_json=input_summary,
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
    row.output_summary_json = output_summary
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
    row.error = error[:2000]
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
) -> LlmCallORM:
    cost: Optional[float] = None
    if input_tokens is not None and output_tokens is not None:
        cost = estimate_cost(model_name, input_tokens, output_tokens)

    row = LlmCallORM(
        id=str(uuid.uuid4()),
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
) -> RetrievalEventORM:
    row = RetrievalEventORM(
        id=str(uuid.uuid4()),
        job_id=job_id,
        cluster_id=cluster_id,
        query=query,
        provider=provider,
        num_candidates=num_candidates,
        num_accepted=num_accepted,
        latency_ms=latency_ms,
        status=status,
        error=error,
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
        "created_at": row.created_at.isoformat(),
    }


def _retrieval_event_dict(row: RetrievalEventORM) -> Dict[str, Any]:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "cluster_id": row.cluster_id,
        "query": row.query,
        "provider": row.provider,
        "num_candidates": row.num_candidates,
        "num_accepted": row.num_accepted,
        "latency_ms": row.latency_ms,
        "status": row.status,
        "error": row.error,
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
    total_llm_calls = db.scalar(select(func.count()).select_from(LlmCallORM)) or 0

    llm_calls_by_status: Dict[str, int] = {}
    for status, count in db.execute(
        select(LlmCallORM.status, func.count()).group_by(LlmCallORM.status)
    ).all():
        llm_calls_by_status[status] = count

    total_tokens = int(
        db.scalar(select(func.sum(LlmCallORM.total_tokens))) or 0
    )

    tokens_by_model: Dict[str, int] = {}
    for model, tok in db.execute(
        select(LlmCallORM.model_name, func.sum(LlmCallORM.total_tokens))
        .group_by(LlmCallORM.model_name)
    ).all():
        tokens_by_model[model] = int(tok or 0)

    raw_cost = db.scalar(select(func.sum(LlmCallORM.estimated_cost_usd)))
    estimated_cost_usd = round(float(raw_cost), 6) if raw_cost is not None else None

    raw_avg_latency = db.scalar(
        select(func.avg(LlmCallORM.latency_ms)).where(LlmCallORM.status == "succeeded")
    )
    average_llm_latency_ms = (
        round(float(raw_avg_latency), 1) if raw_avg_latency is not None else None
    )

    failed_agent_steps = (
        db.scalar(
            select(func.count())
            .select_from(AgentStepORM)
            .where(AgentStepORM.status == "failed")
        )
        or 0
    )

    retrieval_events = (
        db.scalar(select(func.count()).select_from(RetrievalEventORM)) or 0
    )

    raw_ret_latency = db.scalar(
        select(func.avg(RetrievalEventORM.latency_ms)).where(
            RetrievalEventORM.status == "succeeded"
        )
    )
    average_retrieval_latency_ms = (
        round(float(raw_ret_latency), 1) if raw_ret_latency is not None else None
    )

    return {
        "total_llm_calls": total_llm_calls,
        "llm_calls_by_status": llm_calls_by_status,
        "total_tokens": total_tokens,
        "tokens_by_model": tokens_by_model,
        "estimated_cost_usd": estimated_cost_usd,
        "average_llm_latency_ms": average_llm_latency_ms,
        "failed_agent_steps": failed_agent_steps,
        "retrieval_events": retrieval_events,
        "average_retrieval_latency_ms": average_retrieval_latency_ms,
    }
