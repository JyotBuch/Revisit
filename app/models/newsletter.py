from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
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


class NewsletterFeedbackORM(Base):
    __tablename__ = "newsletter_feedback"
    __table_args__ = (
        CheckConstraint("level IN ('newsletter', 'item')", name="ck_newsletter_feedback_level"),
        CheckConstraint("sentiment IN ('useful', 'not_useful')", name="ck_newsletter_feedback_sentiment"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    newsletter_id: Mapped[str] = mapped_column(String, ForeignKey("newsletters.id", ondelete="CASCADE"), nullable=False, index=True)
    capture_id: Mapped[str | None] = mapped_column(String, ForeignKey("captures.id", ondelete="CASCADE"), nullable=True)
    level: Mapped[str] = mapped_column(String, nullable=False)
    sentiment: Mapped[str] = mapped_column(String, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_processed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))


class NewsletterItemRevisionORM(Base):
    __tablename__ = "newsletter_item_revisions"
    __table_args__ = (
        UniqueConstraint("newsletter_id", "capture_id", "version", name="uq_newsletter_item_revision_version"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_newsletter_item_revision_status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    newsletter_id: Mapped[str] = mapped_column(String, ForeignKey("newsletters.id", ondelete="CASCADE"), nullable=False, index=True)
    capture_id: Mapped[str] = mapped_column(String, ForeignKey("captures.id", ondelete="CASCADE"), nullable=False)
    feedback_id: Mapped[str | None] = mapped_column(String, ForeignKey("newsletter_feedback.id", ondelete="SET NULL"), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    content_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    memory_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
