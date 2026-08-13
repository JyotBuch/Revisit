from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator


class CaptureMode(str, Enum):
    research = "research"
    capture = "capture"


class ExtensionGoogleLogin(BaseModel):
    access_token: str = Field(min_length=10)


class ExtensionTokenRead(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_at: int


class MeRead(BaseModel):
    id: str
    email: str
    display_name: str | None = None
    avatar_url: str | None = None
    timezone: str
    nightly_research_enabled: bool
    created_at: datetime


class MeUpdate(BaseModel):
    timezone: str | None = None
    nightly_research_enabled: bool | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value


class PublicCaptureCreate(BaseModel):
    source_type: str = "passage"
    url: str | None = None
    title: str | None = None
    selected_text: str | None = None
    user_note: str | None = None
    domain: str | None = None
    description: str | None = None
    author: str | None = None
    captured_at: datetime | None = None
    mode: CaptureMode
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator("url")
    @classmethod
    def safe_capture_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        from urllib.parse import urlparse
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Capture URL must be an absolute HTTP(S) URL")
        return value
