import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.capture import CaptureORM
from app.models.capture_embedding import CaptureEmbeddingORM
from app.models.cluster import ClusterItemORM, ClusterORM
from app.schemas.cluster import ClusterStatus

DEFAULT_SIMILARITY_THRESHOLD = 0.60


@dataclass
class ClusteringSummary:
    captures_considered: int
    clusters_created: int
    clusters_reused: int
    clusters_archived: int
    assignments_created: int


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    # pgvector may return numpy scalars; cast to a plain float so it's
    # storable as-is (psycopg2 can't adapt numpy.float32/float64).
    return float(dot / (norm_a * norm_b))


def _average_embedding(vectors: List[List[float]]) -> List[float]:
    dim = len(vectors[0])
    return [float(sum(v[i] for v in vectors) / len(vectors)) for i in range(dim)]


def run_clustering(
    db: Session, similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    user_id: str | None = None,
) -> ClusteringSummary:
    """Incrementally update clusters, preserving stable cluster identity.

    Unlike the earlier clear-and-rebuild approach, this never deletes a
    cluster, a cluster_item, or anything downstream (resources, Revisit
    Cards, feedback) tied to one. Each embedded capture is re-evaluated
    against every currently *active* cluster's centroid (the average
    embedding of its current members, recomputed at the end of the
    previous run — or, for clusters from before this embedding existed,
    computed once here from current members as a one-time bootstrap):

    - If a capture matches an active cluster above `similarity_threshold`,
      it's assigned there. If it was already assigned elsewhere,
      `cluster_items.capture_id`'s unique constraint means this updates
      the existing row in place rather than inserting a duplicate.
    - If no active cluster matches, a new cluster is created, seeded with
      this capture as both `representative_capture_id` and the initial
      centroid. New clusters become candidates for *later* captures within
      the same run (so a topic forming mid-run can still absorb more of
      its own members in the same pass) but a cluster's comparison
      embedding is fixed for the duration of one run — it's only
      recomputed once, after the full pass, to avoid order-dependent
      drift within a single run.
    - A cluster that was active going into this run but received zero
      assignments (new or reconfirmed) during it is archived, not
      deleted — its resources, Revisit Cards, and feedback are untouched,
      since nothing about them was ever deleted in this algorithm.

    A cluster's `title` is preserved whenever the cluster is reused; only
    brand-new clusters get a fresh placeholder title.
    """
    captures_query = (
        select(CaptureORM, CaptureEmbeddingORM.embedding)
        .join(CaptureEmbeddingORM, CaptureEmbeddingORM.capture_id == CaptureORM.id)
        .order_by(CaptureORM.created_at)
    )
    if user_id is not None:
        captures_query = captures_query.where(CaptureORM.user_id == user_id)
    rows = db.execute(captures_query).all()
    embedding_by_capture_id: Dict[str, List[float]] = {
        capture.id: embedding for capture, embedding in rows
    }

    cluster_query = (
            select(ClusterORM)
            .where(ClusterORM.status == ClusterStatus.active)
            .options(selectinload(ClusterORM.items))
    )
    if user_id is not None:
        cluster_query = cluster_query.where(ClusterORM.user_id == user_id)
    active_clusters = list(
        db.scalars(
            cluster_query
        ).all()
    )

    existing_items_by_capture_id: Dict[str, ClusterItemORM] = {
        item.capture_id: item
        for cluster in active_clusters
        for item in cluster.items
    }
    members_by_cluster_id: Dict[str, Set[str]] = {
        cluster.id: {item.capture_id for item in cluster.items}
        for cluster in active_clusters
    }

    # Comparison embeddings are fixed for this run (see docstring): each
    # active cluster's stored centroid, falling back to computing one once
    # from its current members for clusters that predate this field.
    live_clusters: List[Tuple[ClusterORM, List[float]]] = []
    for cluster in active_clusters:
        if cluster.centroid_embedding is not None:
            live_clusters.append((cluster, cluster.centroid_embedding))
            continue
        member_embeddings = [
            embedding_by_capture_id[cap_id]
            for cap_id in members_by_cluster_id[cluster.id]
            if cap_id in embedding_by_capture_id
        ]
        if member_embeddings:
            live_clusters.append((cluster, _average_embedding(member_embeddings)))
        # else: no usable embedding to compare against yet — excluded as a
        # candidate this run; it'll simply be treated as untouched below.

    touched_cluster_ids: Set[str] = set()
    new_cluster_ids: Set[str] = set()
    previously_active_ids = {cluster.id for cluster in active_clusters}
    assignments_created = 0
    now = datetime.now(timezone.utc)

    for capture, embedding in rows:
        best_cluster: Optional[ClusterORM] = None
        best_similarity = -1.0
        for cluster, centroid in live_clusters:
            similarity = _cosine_similarity(embedding, centroid)
            if similarity >= similarity_threshold and similarity > best_similarity:
                best_cluster = cluster
                best_similarity = similarity

        if best_cluster is None:
            best_cluster = ClusterORM(
                id=str(uuid.uuid4()),
                user_id=user_id or capture.user_id,
                title=capture.title or "Untitled Cluster",
                representative_capture_id=capture.id,
                centroid_embedding=embedding,
                status=ClusterStatus.active,
                last_clustered_at=now,
            )
            db.add(best_cluster)
            live_clusters.append((best_cluster, embedding))
            members_by_cluster_id[best_cluster.id] = set()
            new_cluster_ids.add(best_cluster.id)
            best_similarity = None

        touched_cluster_ids.add(best_cluster.id)

        existing_item = existing_items_by_capture_id.get(capture.id)
        if existing_item is None:
            db.add(
                ClusterItemORM(
                    id=str(uuid.uuid4()),
                    cluster_id=best_cluster.id,
                    capture_id=capture.id,
                    similarity_score=best_similarity,
                )
            )
            members_by_cluster_id[best_cluster.id].add(capture.id)
            assignments_created += 1
        elif existing_item.cluster_id != best_cluster.id:
            members_by_cluster_id[existing_item.cluster_id].discard(capture.id)
            existing_item.cluster_id = best_cluster.id
            existing_item.similarity_score = best_similarity
            members_by_cluster_id[best_cluster.id].add(capture.id)
            assignments_created += 1
        else:
            existing_item.similarity_score = best_similarity

    clusters_archived = 0
    for cluster in active_clusters:
        if cluster.id in touched_cluster_ids:
            member_embeddings = [
                embedding_by_capture_id[cap_id]
                for cap_id in members_by_cluster_id[cluster.id]
                if cap_id in embedding_by_capture_id
            ]
            if member_embeddings:
                cluster.centroid_embedding = _average_embedding(member_embeddings)
            cluster.last_clustered_at = now
        else:
            cluster.status = ClusterStatus.archived
            clusters_archived += 1

    db.commit()

    clusters_reused = len(touched_cluster_ids & previously_active_ids)

    return ClusteringSummary(
        captures_considered=len(rows),
        clusters_created=len(new_cluster_ids),
        clusters_reused=clusters_reused,
        clusters_archived=clusters_archived,
        assignments_created=assignments_created,
    )


def list_clusters(db: Session, include_archived: bool = False, user_id: str | None = None) -> List[ClusterORM]:
    query = select(ClusterORM).options(
        selectinload(ClusterORM.items).selectinload(ClusterItemORM.capture)
    )
    if not include_archived:
        query = query.where(ClusterORM.status == ClusterStatus.active)
    if user_id is not None:
        query = query.where(ClusterORM.user_id == user_id)
    return list(db.scalars(query.order_by(ClusterORM.created_at)).all())


def get_cluster(db: Session, cluster_id: str, user_id: str | None = None) -> Optional[ClusterORM]:
    query = (
        select(ClusterORM).where(ClusterORM.id == cluster_id)
        .options(selectinload(ClusterORM.items).selectinload(ClusterItemORM.capture))
    )
    if user_id is not None:
        query = query.where(ClusterORM.user_id == user_id)
    return db.scalar(query)
