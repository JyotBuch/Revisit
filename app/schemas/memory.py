from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


MemoryType = Literal["procedural", "semantic", "episodic"]
MemoryStatus = Literal["active", "disabled", "superseded", "deleted"]
FeedbackSentiment = Literal["useful", "not_useful"]


class MemoryRead(BaseModel):
    id: str
    memory_type: MemoryType
    canonical_key: str
    summary: str
    value: dict[str, Any]
    confidence: float
    status: MemoryStatus
    provenance_type: str
    source_links: list[dict[str, str]]
    version: int
    observed_at: datetime | None = None
    stale_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MemoryUpdate(BaseModel):
    summary: str | None = Field(default=None, min_length=1, max_length=2000)
    value: dict[str, Any] | None = None
    status: Literal["active", "disabled"] | None = None


class NewsletterFeedbackCreate(BaseModel):
    sentiment: FeedbackSentiment
    comment: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def require_negative_comment(self):
        if self.sentiment == "not_useful" and not (self.comment or "").strip():
            raise ValueError("A comment is required when feedback is not useful")
        return self


class NewsletterFeedbackRead(BaseModel):
    id: str
    newsletter_id: str
    capture_id: str | None
    level: Literal["newsletter", "item"]
    sentiment: FeedbackSentiment
    comment: str | None
    created_at: datetime


class RevisionRead(BaseModel):
    id: str
    newsletter_id: str
    capture_id: str
    version: int
    status: Literal["queued", "running", "succeeded", "failed"]
    content: dict[str, Any] | None
    created_at: datetime
    completed_at: datetime | None
