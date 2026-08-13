from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.schemas.feedback import FeedbackAction

if TYPE_CHECKING:
    from app.models.revisit_card import RevisitCardORM


class RevisitCardFeedbackORM(Base):
    __tablename__ = "revisit_card_feedback"
    __table_args__ = (
        CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)",
            name="ck_revisit_card_feedback_rating_range",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    revisit_card_id: Mapped[str] = mapped_column(
        String, ForeignKey("revisit_cards.id"), nullable=False
    )
    action: Mapped[FeedbackAction] = mapped_column(
        SAEnum(
            FeedbackAction,
            name="feedback_action",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        )
    )
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    revisit_card: Mapped["RevisitCardORM"] = relationship(back_populates="feedback_events")
