"""Synchronous daily batch — a local/dev skeleton, not a production job.

POST /jobs/daily-batch runs the extract -> embed -> cluster -> retrieve
related resources -> generate-cluster-card pipeline for return-labeled
captures synchronously, within a single HTTP request/response. There is
intentionally no scheduler, no worker process, no queue, and no
retry/backoff here.
Calling the endpoint *is* the schedule, for now — see the README for how
this is meant to evolve into an actual scheduled background job later
without changing the underlying pipeline logic.

Because each step below (extraction, embedding, clustering, card
creation) commits to the database as it goes — consistent with every other
service in this codebase — a mid-batch failure leaves whatever already
committed in place rather than rolling back atomically. That's acceptable
for a synchronous dev skeleton; a real scheduled job would need to think
about idempotent re-runs and partial-failure recovery, which is explicitly
out of scope here.
"""

import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.capture import CaptureORM
from app.schemas.capture import Capture, CaptureLabel, CaptureStatus
from app.schemas.job import Job, JobType
from app.schemas.revisit_card import GenerationMethod
from app.services import (
    capture_store,
    clustering,
    embeddings,
    extraction,
    jobs,
    resource_store,
    retrieval,
    revisit_card_store,
    telemetry,
)

DEFAULT_RESOURCE_LIMIT_PER_CLUSTER = 5

logger = logging.getLogger("revisit.batch")


class DailyBatchError(RuntimeError):
    """Raised when the daily batch fails after the job has been marked failed.

    Carries job_id so the caller (the API layer) can report which job
    record holds the full error detail, without needing its own try/except
    around every sub-step.
    """

    def __init__(self, job_id: str, message: str):
        super().__init__(message)
        self.job_id = job_id


def run_daily_batch(
    db: Session, generation_method: str = "rule_based", *,
    user_id: str | None = None, existing_job_id: str | None = None,
) -> Job:
    if existing_job_id:
        job = jobs.get_job(db, existing_job_id)
        if job is None:
            raise ValueError("Existing job not found")
    else:
        job = jobs.start_job(db, JobType.daily_batch, user_id=user_id)

    batch_step = telemetry.start_agent_step(
        db, job_id=job.id, step_name="daily_batch"
    )

    try:
        method = GenerationMethod(generation_method)

        capture_query = select(CaptureORM).where(CaptureORM.label == CaptureLabel.return_)
        if user_id is not None:
            capture_query = capture_query.where(CaptureORM.user_id == user_id)
        capture_rows = db.scalars(capture_query).all()
        captures_considered = len(capture_rows)
        captures_extracted = 0
        extraction_failures = 0
        embeddings_created = 0

        # Update batch step now we know how many captures we're working on
        batch_step.input_summary_json = {"captures_considered": captures_considered}
        db.flush()

        for row in capture_rows:
            capture = Capture.model_validate(row, from_attributes=True)

            if capture.status == CaptureStatus.saved:
                step = telemetry.start_agent_step(
                    db,
                    job_id=job.id,
                    step_name="extract_capture",
                    owner_type="capture",
                    owner_id=capture.id,
                    input_summary={"status_before": capture.status.value},
                )
                result = extraction.extract_capture_content(capture)
                capture_store.update_extraction(
                    db,
                    capture.id,
                    extracted_text=result.extracted_text,
                    status=result.status,
                    extraction_error=result.extraction_error,
                )
                if result.status == CaptureStatus.extracted:
                    captures_extracted += 1
                    telemetry.complete_agent_step(
                        db, step.id, output_summary={"status_after": "extracted"}
                    )
                else:
                    extraction_failures += 1
                    telemetry.fail_agent_step(
                        db, step.id, error=result.extraction_error or "extraction_failed"
                    )
                db.commit()
                capture = capture_store.get_capture(db, capture.id)

            if capture.extracted_text and embeddings.get_embedding(db, capture.id) is None:
                step = telemetry.start_agent_step(
                    db,
                    job_id=job.id,
                    step_name="embed_capture",
                    owner_type="capture",
                    owner_id=capture.id,
                )
                try:
                    embeddings.create_embedding_for_capture(db, capture.id)
                    embeddings_created += 1
                    telemetry.complete_agent_step(db, step.id)
                except Exception as exc:
                    telemetry.fail_agent_step(db, step.id, error=f"{type(exc).__name__}: {exc}")
                db.commit()

        cluster_step = telemetry.start_agent_step(
            db, job_id=job.id, step_name="run_clustering"
        )
        clustering_summary = clustering.run_clustering(db, user_id=user_id)
        telemetry.complete_agent_step(
            db,
            cluster_step.id,
            output_summary={
                "clusters_created": clustering_summary.clusters_created,
                "clusters_reused": clustering_summary.clusters_reused,
                "clusters_archived": clustering_summary.clusters_archived,
            },
        )
        db.commit()

        clusters = clustering.list_clusters(db, user_id=user_id)

        from app.services import research_agent as ra

        resources_retrieved = 0
        resources_accepted = 0
        research_notes_by_cluster: dict = {}

        for cluster in clusters:
            if method == GenerationMethod.llm:
                step = telemetry.start_agent_step(
                    db,
                    job_id=job.id,
                    step_name="research_agent",
                    owner_type="cluster",
                    owner_id=cluster.id,
                    input_summary={
                        "cluster_title": cluster.title,
                        "limit": DEFAULT_RESOURCE_LIMIT_PER_CLUSTER,
                    },
                )
                notes = ra.run_research(
                    db, cluster, job_id=job.id, limit=DEFAULT_RESOURCE_LIMIT_PER_CLUSTER
                )
                if notes is not None:
                    resources_retrieved += len(notes.sources_used)
                    resources_accepted += len(notes.sources_used)
                    telemetry.complete_agent_step(
                        db,
                        step.id,
                        output_summary={
                            "iterations_used": notes.iterations_used,
                            "sources_read": len(notes.sources_used),
                            "model": notes.model,
                        },
                    )
                    research_notes_by_cluster[cluster.id] = notes
                else:
                    # Agent unavailable or timed out — fall back to single-search retrieval
                    telemetry.fail_agent_step(
                        db, step.id, error="research_agent_unavailable_or_incomplete"
                    )
                    retrieval_summary = retrieval.retrieve_and_store_resources_for_cluster(
                        db, cluster.id, limit=DEFAULT_RESOURCE_LIMIT_PER_CLUSTER, job_id=job.id
                    )
                    if retrieval_summary is not None:
                        resources_retrieved += retrieval_summary.resources_retrieved
                        resources_accepted += retrieval_summary.resources_accepted
                    research_notes_by_cluster[cluster.id] = None
            else:
                step = telemetry.start_agent_step(
                    db,
                    job_id=job.id,
                    step_name="retrieve_resources",
                    owner_type="cluster",
                    owner_id=cluster.id,
                    input_summary={"limit": DEFAULT_RESOURCE_LIMIT_PER_CLUSTER},
                )
                retrieval_summary = retrieval.retrieve_and_store_resources_for_cluster(
                    db, cluster.id, limit=DEFAULT_RESOURCE_LIMIT_PER_CLUSTER, job_id=job.id
                )
                if retrieval_summary is not None:
                    resources_retrieved += retrieval_summary.resources_retrieved
                    resources_accepted += retrieval_summary.resources_accepted
                    telemetry.complete_agent_step(
                        db,
                        step.id,
                        output_summary={
                            "num_retrieved": retrieval_summary.resources_retrieved,
                            "num_accepted": retrieval_summary.resources_accepted,
                        },
                    )
                else:
                    telemetry.fail_agent_step(db, step.id, error="cluster_not_found")
                research_notes_by_cluster[cluster.id] = None
            db.commit()

        cards_created = 0
        cards_reused = 0
        cards_with_resources = 0
        for cluster in clusters:
            existing_card = revisit_card_store.get_latest_card_for_cluster(db, cluster.id)
            if (
                existing_card is not None
                and cluster.last_clustered_at is not None
                and existing_card.created_at >= cluster.last_clustered_at
            ):
                # A card already reflects this cluster's current state —
                # nothing about the cluster has changed since it was made.
                cards_reused += 1
                if resource_store.list_resources_for_card(db, existing_card.id):
                    cards_with_resources += 1
                continue

            step = telemetry.start_agent_step(
                db,
                job_id=job.id,
                step_name="generate_revisit_card",
                owner_type="cluster",
                owner_id=cluster.id,
                input_summary={"generation_method": generation_method},
            )
            try:
                card = revisit_card_store.create_revisit_card_for_cluster(
                    db,
                    cluster,
                    generation_method=method,
                    include_resources=True,
                    job_id=job.id,
                    research_notes=research_notes_by_cluster.get(cluster.id),
                )
                cards_created += 1
                has_resources = bool(resource_store.list_resources_for_card(db, card.id))
                if has_resources:
                    cards_with_resources += 1
                telemetry.complete_agent_step(
                    db,
                    step.id,
                    output_summary={
                        "card_id": card.id,
                        "method_used": card.generation_method.value,
                        "has_resources": has_resources,
                    },
                )
            except Exception as exc:
                telemetry.fail_agent_step(db, step.id, error=f"{type(exc).__name__}: {exc}")
            db.commit()

        summary: Dict[str, Any] = {
            "research_agent_runs": sum(
                1 for v in research_notes_by_cluster.values() if v is not None
            ),
            "captures_considered": captures_considered,
            "captures_extracted": captures_extracted,
            "extraction_failures": extraction_failures,
            "embeddings_created": embeddings_created,
            "clusters_created": clustering_summary.clusters_created,
            "clusters_reused": clustering_summary.clusters_reused,
            "clusters_archived": clustering_summary.clusters_archived,
            "resources_retrieved": resources_retrieved,
            "resources_accepted": resources_accepted,
            "cards_created": cards_created,
            "cards_reused": cards_reused,
            "cards_with_resources": cards_with_resources,
            "generation_method_requested": generation_method,
        }

        telemetry.complete_agent_step(db, batch_step.id, output_summary=summary)
        db.commit()

        return jobs.complete_job(db, job.id, summary)

    except Exception as exc:
        logger.exception("daily_batch_failed job_id=%s", job.id)
        try:
            telemetry.fail_agent_step(db, batch_step.id, error=f"{type(exc).__name__}: {exc}")
            db.commit()
        except Exception:
            pass
        jobs.fail_job(db, job.id, f"{type(exc).__name__}: {exc}")
        raise DailyBatchError(job.id, str(exc)) from exc
