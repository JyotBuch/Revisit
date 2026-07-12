import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.resource import ResourceRead


class CardType(str, Enum):
    individual = "individual"
    cluster = "cluster"


class GenerationMethod(str, Enum):
    rule_based = "rule_based"
    llm = "llm"


class RevisitCardRead(BaseModel):
    id: str
    capture_id: Optional[str] = None
    cluster_id: Optional[str] = None
    card_type: CardType
    generation_method: GenerationMethod
    model_name: Optional[str] = None
    prompt_version: Optional[str] = None
    title: str
    why_saved: str
    original_context: Optional[str] = None
    next_action: str
    resources: List[ResourceRead] = []
    created_at: datetime


class RevisitCard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    capture_id: Optional[str] = None
    cluster_id: Optional[str] = None
    card_type: CardType
    generation_method: GenerationMethod = GenerationMethod.rule_based
    model_name: Optional[str] = None
    prompt_version: Optional[str] = None
    title: str
    why_saved: str
    original_context: Optional[str] = None
    next_action: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
