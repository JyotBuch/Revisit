"""Free-tier adapter for manually running a research job in the web process.

This is intentionally a testing mode. A process restart can interrupt the task;
the paid deployment should use the dedicated leasing worker instead.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models.job import JobORM
from app.schemas.job import JobStatus
from app.services.newsletter import run_item_revision, run_newsletter_batch

logger = logging.getLogger("revisit.inline_research")


def run_inline_research_job(job_id: str, user_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.scalar(
            select(JobORM)
            .where(
                JobORM.id == job_id,
                JobORM.user_id == user_id,
                JobORM.status == JobStatus.queued,
            )
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return
        now = datetime.now(timezone.utc)
        job.status = JobStatus.running
        job.attempts += 1
        job.worker_id = "inline-free-tier"
        job.lease_expires_at = now + timedelta(minutes=15)
        job.started_at = now
        db.commit()
        run_newsletter_batch(db, user_id=user_id, job_id=job_id)
    except Exception:
        logger.exception("inline_research_job_failed job_id=%s", job_id)
    finally:
        db.close()


def run_inline_revision_job(job_id: str, revision_id: str, user_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.scalar(select(JobORM).where(
            JobORM.id == job_id, JobORM.user_id == user_id,
            JobORM.status == JobStatus.queued,
        ).with_for_update(skip_locked=True))
        if job is None:
            return
        now = datetime.now(timezone.utc)
        job.status = JobStatus.running
        job.attempts += 1
        job.worker_id = "inline-free-tier"
        job.lease_expires_at = now + timedelta(minutes=15)
        job.started_at = now
        db.commit()
        run_item_revision(db, revision_id=revision_id, user_id=user_id)
    except Exception:
        logger.exception("inline_revision_job_failed job_id=%s revision_id=%s", job_id, revision_id)
    finally:
        db.close()
