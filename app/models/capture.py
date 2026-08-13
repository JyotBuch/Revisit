from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.schemas.capture import CaptureLabel, CaptureStatus, SourceType

if TYPE_CHECKING:
    from app.models.revisit_card import RevisitCardORM


class CaptureORM(Base):
    __tablename__ = "captures"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    domain: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(nullable=True)
    source_type: Mapped[SourceType] = mapped_column(
        SAEnum(
            SourceType,
            name="source_type",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        )
    )
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    selected_text: Mapped[str | None] = mapped_column(String, nullable=True)
    user_note: Mapped[str | None] = mapped_column(String, nullable=True)
    label: Mapped[CaptureLabel] = mapped_column(
        SAEnum(
            CaptureLabel,
            name="label",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        )
    )
    status: Mapped[CaptureStatus] = mapped_column(
        SAEnum(
            CaptureStatus,
            name="status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=CaptureStatus.saved,
    )
    extracted_text: Mapped[str | None] = mapped_column(String, nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    revisit_cards: Mapped[list["RevisitCardORM"]] = relationship(
        back_populates="capture", cascade="all, delete-orphan"
    )
