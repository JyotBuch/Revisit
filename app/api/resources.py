from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_auth, require_legacy_pipeline_disabled_in_production
from app.models.user import UserORM
from app.db import get_db
from app.schemas.resource import ResourceRead
from app.services import clustering, resource_store, retrieval

router = APIRouter(tags=["resources"], dependencies=[Depends(require_legacy_pipeline_disabled_in_production)])


@router.post("/clusters/{cluster_id}/resources", response_model=list[ResourceRead])
def retrieve_resources(
    cluster_id: str,
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
    user: UserORM | None = Depends(require_auth),
) -> list[ResourceRead]:
    if clustering.get_cluster(db, cluster_id, user_id=user.id if user else None) is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    summary = retrieval.retrieve_and_store_resources_for_cluster(
        db, cluster_id, limit=limit
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return [ResourceRead(**r.model_dump()) for r in summary.resources]


@router.get("/clusters/{cluster_id}/resources", response_model=list[ResourceRead])
def list_resources(cluster_id: str, db: Session = Depends(get_db), user: UserORM | None = Depends(require_auth)) -> list[ResourceRead]:
    cluster = clustering.get_cluster(db, cluster_id, user_id=user.id if user else None)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found")

    return [
        ResourceRead(**r.model_dump())
        for r in resource_store.list_resources_for_cluster(db, cluster_id)
    ]
