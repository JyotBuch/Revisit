from datetime import datetime

from pydantic import BaseModel, Field


class NewsletterSource(BaseModel):
    title: str
    url: str


class NewsletterItem(BaseModel):
    capture_id: str
    research_question: str | None = None
    title: str
    saved_text: str
    research_summary: str
    next_question: str
    sources: list[NewsletterSource]
    revision_id: str | None = None
    revision_version: int = 0
    revision_history: list[dict] = Field(default_factory=list)


class NewsletterRead(BaseModel):
    id: str
    subject: str
    introduction: str | None = None
    items: list[NewsletterItem]
    created_at: datetime
