"""Postgres-backed research worker.

Run with ``python -m app.worker``. Jobs are leased atomically so a crashed
worker can be replaced without running two copies for the same user.
"""

import logging
import os
import socket
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models.job import JobORM
from app.schemas.job import JobStatus
from app.services.newsletter import run_newsletter_batch

logger = logging.getLogger("revisit.worker")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def claim_job():
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        job = db.scalar(
            select(JobORM)
            .where(
                JobORM.status == JobStatus.queued,
                JobORM.available_at <= now,
                JobORM.attempts < JobORM.max_attempts,
            )
            .order_by(JobORM.available_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            db.close()
            return None
        job.status = JobStatus.running
        job.attempts += 1
        job.worker_id = WORKER_ID
        job.lease_expires_at = now + timedelta(minutes=30)
        job.started_at = now
        db.commit()
        db.refresh(job)
        return db, job
    except Exception:
        db.rollback()
        db.close()
        raise


def recover_expired_leases() -> None:
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        rows = db.scalars(select(JobORM).where(
            JobORM.status == JobStatus.running, JobORM.lease_expires_at < now
        )).all()
        for job in rows:
            if job.attempts >= job.max_attempts:
                job.status = JobStatus.failed
                job.error = "Worker lease expired and retry limit was reached"
                job.completed_at = now
            else:
                job.status = JobStatus.queued
                job.available_at = now + timedelta(seconds=30 * job.attempts)
                job.worker_id = None
                job.lease_expires_at = None
        db.commit()
    finally:
        db.close()


def run_forever() -> None:
    while True:
        recover_expired_leases()
        claimed = claim_job()
        if claimed is None:
            time.sleep(2)
            continue
        db, job = claimed
        try:
            run_newsletter_batch(db, user_id=job.user_id, job_id=job.id)
        except Exception:
            logger.exception("research_job_failed job_id=%s", job.id)
        finally:
            db.close()


if __name__ == "__main__":
    run_forever()
