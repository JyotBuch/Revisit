import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, Field, field_validator


class FeedbackAction(str, Enum):
    opened = "opened"
    useful = "useful"
    not_useful = "not_useful"
    dismissed = "dismissed"
    next_action_taken = "next_action_taken"


class RevisitCardFeedbackCreate(BaseModel):
    action: FeedbackAction
    rating: Optional[int] = None
    comment: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def rating_in_range(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and not (1 <= value <= 5):
            raise ValueError("rating must be between 1 and 5")
        return value


class RevisitCardFeedbackRead(BaseModel):
    id: str
    revisit_card_id: str
    action: FeedbackAction
    rating: Optional[int] = None
    comment: Optional[str] = None
    created_at: datetime


class RevisitCardFeedback(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    revisit_card_id: str
    action: FeedbackAction
    rating: Optional[int] = None
    comment: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FeedbackSummary(BaseModel):
    total_feedback_events: int
    counts_by_action: Dict[str, int]
    average_rating: Optional[float] = None
    useful_rate: Optional[float] = None
    dismiss_rate: Optional[float] = None
