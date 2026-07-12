from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel

from app.schemas.capture import CaptureRead


class ClusterStatus(str, Enum):
    active = "active"
    archived = "archived"


class ClusterCaptureItem(BaseModel):
    capture: CaptureRead
    similarity_score: Optional[float] = None


class ClusterRead(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    status: ClusterStatus
    representative_capture_id: Optional[str] = None
    last_clustered_at: Optional[datetime] = None
    captures: List[ClusterCaptureItem] = []
    created_at: datetime
    updated_at: datetime


class ClusterRunResult(BaseModel):
    captures_considered: int
    clusters_created: int
    clusters_reused: int
    clusters_archived: int
    assignments_created: int
