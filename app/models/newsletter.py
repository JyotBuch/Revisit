from datetime import datetime, timezone

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class NewsletterORM(Base):
    __tablename__ = "newsletters"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[str | None] = mapped_column(String, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    introduction: Mapped[str | None] = mapped_column(Text, nullable=True)
    items_json: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))


class NewsletterCaptureORM(Base):
    __tablename__ = "newsletter_captures"
    __table_args__ = (UniqueConstraint("capture_id", name="uq_newsletter_capture"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    newsletter_id: Mapped[str] = mapped_column(String, ForeignKey("newsletters.id", ondelete="CASCADE"), nullable=False)
    capture_id: Mapped[str] = mapped_column(String, ForeignKey("captures.id", ondelete="CASCADE"), nullable=False)
