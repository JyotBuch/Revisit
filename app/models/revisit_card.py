from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.schemas.revisit_card import CardType, GenerationMethod

if TYPE_CHECKING:
    from app.models.capture import CaptureORM
    from app.models.cluster import ClusterORM
    from app.models.revisit_card_feedback import RevisitCardFeedbackORM
    from app.models.revisit_card_resource import RevisitCardResourceORM


class RevisitCardORM(Base):
    __tablename__ = "revisit_cards"
    __table_args__ = (
        CheckConstraint(
            "(capture_id IS NOT NULL AND cluster_id IS NULL) OR "
            "(capture_id IS NULL AND cluster_id IS NOT NULL)",
            name="ck_revisit_cards_exactly_one_owner",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    capture_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("captures.id"), nullable=True
    )
    cluster_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("clusters.id"), nullable=True
    )
    card_type: Mapped[CardType] = mapped_column(
        SAEnum(
            CardType,
            name="card_type",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        server_default=CardType.individual.value,
    )
    generation_method: Mapped[GenerationMethod] = mapped_column(
        SAEnum(
            GenerationMethod,
            name="generation_method",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        server_default=GenerationMethod.rule_based.value,
    )
    model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String)
    why_saved: Mapped[str] = mapped_column(String)
    original_context: Mapped[str | None] = mapped_column(String, nullable=True)
    next_action: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    capture: Mapped["CaptureORM | None"] = relationship(back_populates="revisit_cards")
    cluster: Mapped["ClusterORM | None"] = relationship()
    feedback_events: Mapped[list["RevisitCardFeedbackORM"]] = relationship(
        back_populates="revisit_card", cascade="all, delete-orphan"
    )
    resource_links: Mapped[list["RevisitCardResourceORM"]] = relationship(
        back_populates="revisit_card", cascade="all, delete-orphan"
    )
