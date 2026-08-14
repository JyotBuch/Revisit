from datetime import date, datetime, timezone

from sqlalchemy import Date, JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LlmCallORM(Base):
    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    job_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    owner_type: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String, nullable=True)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    failure_type: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    response_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    response_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )


class AgentStepORM(Base):
    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    job_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    step_name: Mapped[str] = mapped_column(String, nullable=False)
    owner_type: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)


class RetrievalEventORM(Base):
    __tablename__ = "retrieval_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    job_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    cluster_id: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_type: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String, nullable=True)
    query: Mapped[str | None] = mapped_column(String, nullable=True)
    query_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    query_intent: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    num_candidates: Mapped[int | None] = mapped_column(Integer, nullable=True)
    num_accepted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    memory_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    memory_scores_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )


class TelemetryDailyAggregateORM(Base):
    __tablename__ = "telemetry_daily_aggregates"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
