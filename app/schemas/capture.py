from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class SourceType(str, Enum):
    article = "article"
    passage = "passage"
    video = "video"
    image = "image"
    note = "note"


class CaptureLabel(str, Enum):
    casual = "casual"
    return_ = "return"


class CaptureStatus(str, Enum):
    saved = "saved"
    extracted = "extracted"
    failed = "failed"


class CaptureCreate(BaseModel):
    source_type: SourceType
    url: Optional[str] = None
    title: Optional[str] = None
    selected_text: Optional[str] = None
    user_note: Optional[str] = None
    label: CaptureLabel

    @model_validator(mode="after")
    def require_some_content(self) -> "CaptureCreate":
        if not (self.url or self.selected_text or self.user_note):
            raise ValueError(
                "At least one of url, selected_text, or user_note must be present"
            )
        return self


class CaptureRead(BaseModel):
    id: str
    source_type: SourceType
    url: Optional[str] = None
    title: Optional[str] = None
    selected_text: Optional[str] = None
    user_note: Optional[str] = None
    label: CaptureLabel
    status: CaptureStatus
    extracted_text: Optional[str] = None
    extraction_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class Capture(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: SourceType
    url: Optional[str] = None
    title: Optional[str] = None
    selected_text: Optional[str] = None
    user_note: Optional[str] = None
    label: CaptureLabel
    status: CaptureStatus = CaptureStatus.saved
    extracted_text: Optional[str] = None
    extraction_error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
