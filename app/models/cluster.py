from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.capture_embedding import EMBEDDING_DIM
from app.schemas.cluster import ClusterStatus

if TYPE_CHECKING:
    from app.models.capture import CaptureORM
    from app.models.resource import ResourceORM


class ClusterORM(Base):
    __tablename__ = "clusters"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    representative_capture_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("captures.id"), nullable=True
    )
    centroid_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
    status: Mapped[ClusterStatus] = mapped_column(
        SAEnum(
            ClusterStatus,
            name="cluster_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        server_default=ClusterStatus.active.value,
    )
    last_clustered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    items: Mapped[list["ClusterItemORM"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )
    resources: Mapped[list["ResourceORM"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )


class ClusterItemORM(Base):
    __tablename__ = "cluster_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    cluster_id: Mapped[str] = mapped_column(
        String, ForeignKey("clusters.id"), nullable=False
    )
    capture_id: Mapped[str] = mapped_column(
        String, ForeignKey("captures.id"), unique=True, nullable=False
    )
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    cluster: Mapped["ClusterORM"] = relationship(back_populates="items")
    capture: Mapped["CaptureORM"] = relationship()
