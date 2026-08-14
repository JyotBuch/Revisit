from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AgentMemoryORM(Base):
    __tablename__ = "agent_memories"
    __table_args__ = (
        CheckConstraint("memory_type IN ('procedural', 'semantic', 'episodic')", name="ck_agent_memory_type"),
        CheckConstraint("status IN ('active', 'disabled', 'superseded', 'deleted')", name="ck_agent_memory_status"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_agent_memory_confidence"),
        UniqueConstraint("user_id", "canonical_key", "version", name="uq_agent_memory_user_key_version"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    canonical_key: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active", index=True)
    provenance_type: Mapped[str] = mapped_column(String, nullable=False)
    provenance_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_links_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    stale_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
