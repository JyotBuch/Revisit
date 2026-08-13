import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class JobType(str, Enum):
    daily_batch = "daily_batch"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class JobRead(BaseModel):
    id: str
    job_type: JobType
    status: JobStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    summary_json: Optional[Dict[str, Any]] = None


class Job(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_type: JobType
    status: JobStatus = JobStatus.running
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    summary_json: Optional[Dict[str, Any]] = None
