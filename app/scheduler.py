"""Enqueue due nightly research jobs. Intended to run hourly."""

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db import SessionLocal
from app.models.job import JobORM
from app.models.user import UserORM
from app.schemas.job import JobStatus, JobType
from app.services import telemetry


def enqueue_due() -> int:
    db = SessionLocal()
    count = 0
    try:
        if telemetry.enabled():
            try:
                telemetry.purge_expired(db)
            except Exception:
                db.rollback()
        now = datetime.now(timezone.utc)
        users = db.scalars(select(UserORM).where(UserORM.nightly_research_enabled.is_(True))).all()
        for user in users:
            local = now.astimezone(ZoneInfo(user.timezone))
            date_key = local.date().isoformat()
            if local.hour != 2 or user.last_nightly_run_date == date_key:
                continue
            active = db.scalar(select(JobORM.id).where(
                JobORM.user_id == user.id,
                JobORM.status.in_([JobStatus.queued, JobStatus.running]),
            ))
            if active:
                continue
            db.add(JobORM(
                id=str(uuid.uuid4()), user_id=user.id, job_type=JobType.daily_batch,
                status=JobStatus.queued, available_at=now,
            ))
            user.last_nightly_run_date = date_key
            count += 1
        db.commit()
        return count
    finally:
        db.close()


if __name__ == "__main__":
    print(f"enqueued={enqueue_due()}")
