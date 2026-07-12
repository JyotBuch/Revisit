import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class ResourceRead(BaseModel):
    id: str
    cluster_id: str
    url: str
    title: str
    source_type: Optional[str] = None
    snippet: Optional[str] = None
    query: Optional[str] = None
    relevance_score: Optional[float] = None
    validation_score: Optional[float] = None
    validation_reason: Optional[str] = None
    provider: Optional[str] = None
    created_at: datetime


class Resource(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cluster_id: str
    url: str
    title: str
    source_type: Optional[str] = None
    snippet: Optional[str] = None
    query: Optional[str] = None
    relevance_score: Optional[float] = None
    validation_score: Optional[float] = None
    validation_reason: Optional[str] = None
    provider: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResourceCandidate(BaseModel):
    """A not-yet-validated/not-yet-stored resource returned by a provider."""

    url: str
    title: str
    source_type: Optional[str] = None
    snippet: Optional[str] = None
    query: Optional[str] = None
    provider: Optional[str] = None
