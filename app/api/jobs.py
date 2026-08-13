from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_auth, require_legacy_pipeline_disabled_in_production
from app.models.user import UserORM
from app.db import get_db
from app.schemas.job import JobRead
from app.schemas.revisit_card import GenerationMethod
from app.services import batch, jobs

router = APIRouter(tags=["jobs"], dependencies=[Depends(require_legacy_pipeline_disabled_in_production)])


@router.post("/jobs/daily-batch", response_model=JobRead)
def run_daily_batch(
    generation_method: GenerationMethod = Query(default=GenerationMethod.rule_based),
    db: Session = Depends(get_db),
    user: UserORM | None = Depends(require_auth),
) -> JobRead:
    try:
        job = batch.run_daily_batch(db, generation_method=generation_method.value, user_id=user.id if user else None)
    except batch.DailyBatchError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Daily batch failed",
                "job_id": exc.job_id,
                "error": str(exc),
            },
        ) from exc
    return JobRead(**job.model_dump())


@router.get("/jobs", response_model=list[JobRead])
def list_jobs(db: Session = Depends(get_db), user: UserORM | None = Depends(require_auth)) -> list[JobRead]:
    return [JobRead(**j.model_dump()) for j in jobs.list_jobs(db, user_id=user.id if user else None)]


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Session = Depends(get_db), user: UserORM | None = Depends(require_auth)) -> JobRead:
    job = jobs.get_job(db, job_id, user_id=user.id if user else None)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobRead(**job.model_dump())
