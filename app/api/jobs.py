from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db import get_db
from app.schemas.job import JobRead
from app.schemas.revisit_card import GenerationMethod
from app.services import batch, jobs

router = APIRouter(tags=["jobs"])


@router.post("/jobs/daily-batch", response_model=JobRead)
def run_daily_batch(
    generation_method: GenerationMethod = Query(default=GenerationMethod.rule_based),
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
) -> JobRead:
    try:
        job = batch.run_daily_batch(db, generation_method=generation_method.value)
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
def list_jobs(db: Session = Depends(get_db)) -> list[JobRead]:
    return [JobRead(**j.model_dump()) for j in jobs.list_jobs(db)]


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobRead:
    job = jobs.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobRead(**job.model_dump())
