import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.job import JobORM
from app.schemas.job import Job, JobStatus, JobType


def start_job(db: Session, job_type: JobType) -> Job:
    row = JobORM(id=str(uuid.uuid4()), job_type=job_type, status=JobStatus.running)
    db.add(row)
    db.commit()
    db.refresh(row)
    return Job.model_validate(row, from_attributes=True)


def complete_job(db: Session, job_id: str, summary: Dict[str, Any]) -> Optional[Job]:
    row = db.get(JobORM, job_id)
    if row is None:
        return None
    row.status = JobStatus.succeeded
    row.completed_at = datetime.now(timezone.utc)
    row.summary_json = summary
    db.commit()
    db.refresh(row)
    return Job.model_validate(row, from_attributes=True)


def fail_job(db: Session, job_id: str, error: str) -> Optional[Job]:
    row = db.get(JobORM, job_id)
    if row is None:
        return None
    row.status = JobStatus.failed
    row.completed_at = datetime.now(timezone.utc)
    row.error = error
    db.commit()
    db.refresh(row)
    return Job.model_validate(row, from_attributes=True)


def list_jobs(db: Session) -> List[Job]:
    rows = db.scalars(select(JobORM).order_by(JobORM.started_at.desc())).all()
    return [Job.model_validate(row, from_attributes=True) for row in rows]


def get_job(db: Session, job_id: str) -> Optional[Job]:
    row = db.get(JobORM, job_id)
    if row is None:
        return None
    return Job.model_validate(row, from_attributes=True)
