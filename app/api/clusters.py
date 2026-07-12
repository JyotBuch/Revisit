from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db import get_db
from app.schemas.capture import Capture, CaptureRead
from app.schemas.cluster import ClusterCaptureItem, ClusterRead, ClusterRunResult
from app.services import clustering

router = APIRouter(prefix="/clusters", tags=["clusters"])


def _to_cluster_read(cluster) -> ClusterRead:
    return ClusterRead(
        id=cluster.id,
        title=cluster.title,
        description=cluster.description,
        status=cluster.status,
        representative_capture_id=cluster.representative_capture_id,
        last_clustered_at=cluster.last_clustered_at,
        captures=[
            ClusterCaptureItem(
                capture=CaptureRead(
                    **Capture.model_validate(item.capture, from_attributes=True).model_dump()
                ),
                similarity_score=item.similarity_score,
            )
            for item in cluster.items
        ],
        created_at=cluster.created_at,
        updated_at=cluster.updated_at,
    )


@router.post("/run", response_model=ClusterRunResult)
def run_clustering(
    similarity_threshold: float = Query(
        default=clustering.DEFAULT_SIMILARITY_THRESHOLD, ge=0.0, le=1.0
    ),
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
) -> ClusterRunResult:
    summary = clustering.run_clustering(db, similarity_threshold=similarity_threshold)
    return ClusterRunResult(
        captures_considered=summary.captures_considered,
        clusters_created=summary.clusters_created,
        clusters_reused=summary.clusters_reused,
        clusters_archived=summary.clusters_archived,
        assignments_created=summary.assignments_created,
    )


@router.get("", response_model=list[ClusterRead])
def list_clusters(
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[ClusterRead]:
    return [
        _to_cluster_read(cluster)
        for cluster in clustering.list_clusters(db, include_archived=include_archived)
    ]


@router.get("/{cluster_id}", response_model=ClusterRead)
def get_cluster(cluster_id: str, db: Session = Depends(get_db)) -> ClusterRead:
    cluster = clustering.get_cluster(db, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return _to_cluster_read(cluster)
