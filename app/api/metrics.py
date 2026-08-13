import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.auth import require_auth
from app.schemas.metrics import ObservabilityMetrics
from app.services import metrics as metrics_service

router = APIRouter(tags=["metrics"])


@router.get("/metrics/observability", response_model=ObservabilityMetrics)
def get_observability_metrics(db: Session = Depends(get_db), _=Depends(require_auth)) -> ObservabilityMetrics:
    if os.environ.get("ENVIRONMENT") == "production":
        raise HTTPException(status_code=404, detail="Not found")
    return ObservabilityMetrics(**metrics_service.get_observability_metrics(db))
