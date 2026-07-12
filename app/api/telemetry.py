from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.telemetry import LlmCallORM
from app.services import telemetry as telemetry_service

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


class TelemetrySummary(BaseModel):
    total_llm_calls: int
    llm_calls_by_status: Dict[str, int]
    total_tokens: int
    tokens_by_model: Dict[str, int]
    estimated_cost_usd: Optional[float]
    average_llm_latency_ms: Optional[float]
    failed_agent_steps: int
    retrieval_events: int
    average_retrieval_latency_ms: Optional[float]


class LlmCallRow(BaseModel):
    id: str
    job_id: Optional[str]
    owner_type: Optional[str]
    owner_id: Optional[str]
    purpose: str
    model_name: str
    prompt_version: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    estimated_cost_usd: Optional[float]
    latency_ms: Optional[int]
    status: str
    failure_type: Optional[str]
    created_at: str


@router.get("/summary", response_model=TelemetrySummary)
def get_summary(db: Session = Depends(get_db)) -> TelemetrySummary:
    return TelemetrySummary(**telemetry_service.get_telemetry_summary(db))


@router.get("/jobs/{job_id}/trace")
def get_job_trace(job_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return telemetry_service.get_job_trace(db, job_id)


@router.get("/llm-calls", response_model=List[LlmCallRow])
def list_llm_calls(
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[LlmCallRow]:
    rows = db.scalars(
        select(LlmCallORM).order_by(LlmCallORM.created_at.desc()).limit(limit)
    ).all()
    return [
        LlmCallRow(
            id=r.id,
            job_id=r.job_id,
            owner_type=r.owner_type,
            owner_id=r.owner_id,
            purpose=r.purpose,
            model_name=r.model_name,
            prompt_version=r.prompt_version,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            total_tokens=r.total_tokens,
            estimated_cost_usd=r.estimated_cost_usd,
            latency_ms=r.latency_ms,
            status=r.status,
            failure_type=r.failure_type,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]
