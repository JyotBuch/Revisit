from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.cluster import ClusterORM


class ResourceORM(Base):
    __tablename__ = "resources"
    __table_args__ = (
        UniqueConstraint("cluster_id", "url", name="uq_resources_cluster_id_url"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    cluster_id: Mapped[str] = mapped_column(
        String, ForeignKey("clusters.id"), nullable=False
    )
    url: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str | None] = mapped_column(String, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    query: Mapped[str | None] = mapped_column(String, nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    validation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    validation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    cluster: Mapped["ClusterORM"] = relationship(back_populates="resources")
