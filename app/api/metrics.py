from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.metrics import ObservabilityMetrics
from app.services import metrics as metrics_service

router = APIRouter(tags=["metrics"])


@router.get("/metrics/observability", response_model=ObservabilityMetrics)
def get_observability_metrics(db: Session = Depends(get_db)) -> ObservabilityMetrics:
    return ObservabilityMetrics(**metrics_service.get_observability_metrics(db))
