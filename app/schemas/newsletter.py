from datetime import datetime

from pydantic import BaseModel


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


class NewsletterRead(BaseModel):
    id: str
    subject: str
    introduction: str | None = None
    items: list[NewsletterItem]
    created_at: datetime
