import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import auth
from app.db import get_db
from app.models.capture import CaptureORM
from app.models.job import JobORM
from app.models.memory import AgentMemoryORM
from app.models.newsletter import NewsletterFeedbackORM, NewsletterItemRevisionORM, NewsletterORM
from app.models.telemetry import AgentStepORM, LlmCallORM, RetrievalEventORM
from app.models.revisit_card import RevisitCardORM
from app.models.user import ExtensionTokenORM, IdempotencyKeyORM, UserORM
from app.schemas.account import (
    ExtensionGoogleLogin, ExtensionTokenRead, MeRead, MeUpdate, PublicCaptureCreate,
)
from app.schemas.capture import CaptureLabel, CaptureRead, SourceType
from app.schemas.job import JobRead, JobStatus, JobType
from app.schemas.newsletter import NewsletterRead
from app.schemas.memory import (
    MemoryRead, MemoryUpdate, NewsletterFeedbackCreate, NewsletterFeedbackRead, RevisionRead,
)
from app.schemas.revisit_card import RevisitCardRead
from app.services import memory as memory_service
from app.services import resource_store
from app.services.inline_research import run_inline_research_job, run_inline_revision_job

router = APIRouter(prefix="/api/v1", tags=["public-api"])


def _google_profile(access_token: str) -> dict:
    try:
        token_response = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"access_token": access_token}, timeout=10,
        )
        token_response.raise_for_status()
        token_info = token_response.json()
        expected_client_id = os.environ.get("GOOGLE_EXTENSION_CLIENT_ID")
        if not expected_client_id or token_info.get("aud") != expected_client_id:
            raise HTTPException(status_code=401, detail="Google credential audience is invalid")
        if int(token_info.get("expires_in", "0")) <= 0:
            raise HTTPException(status_code=401, detail="Google credential has expired")
        response = requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}, timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except HTTPException:
        raise
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid Google credential") from exc


@router.post("/auth/extension/google", response_model=ExtensionTokenRead)
def extension_google_login(body: ExtensionGoogleLogin) -> ExtensionTokenRead:
    user = auth.upsert_google_user(_google_profile(body.access_token))
    token, expires_at = auth.issue_extension_token(user.id)
    return ExtensionTokenRead(token=token, expires_at=expires_at)


@router.delete("/auth/extension/tokens/current", status_code=204)
def revoke_extension_token(
    request: Request,
    _: UserORM = Depends(auth.current_user),
    db: Session = Depends(get_db),
) -> Response:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        row = db.scalar(select(ExtensionTokenORM).where(
            ExtensionTokenORM.token_hash == auth.token_hash(authorization.split(" ", 1)[1])
        ))
        if row:
            row.revoked_at = datetime.now(timezone.utc)
            db.commit()
    return Response(status_code=204)


@router.get("/me", response_model=MeRead)
def get_me(user: UserORM = Depends(auth.current_user)) -> MeRead:
    return MeRead.model_validate(user, from_attributes=True)


@router.patch("/me", response_model=MeRead)
def update_me(
    body: MeUpdate,
    user: UserORM = Depends(auth.current_user),
    db: Session = Depends(get_db),
) -> MeRead:
    row = db.get(UserORM, user.id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return MeRead.model_validate(row, from_attributes=True)


@router.get("/me/export")
def export_account(
    user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db),
) -> dict:
    captures = db.scalars(select(CaptureORM).where(CaptureORM.user_id == user.id)).all()
    newsletters = db.scalars(select(NewsletterORM).where(NewsletterORM.user_id == user.id)).all()
    feedback = db.scalars(select(NewsletterFeedbackORM).where(NewsletterFeedbackORM.user_id == user.id)).all()
    memories = db.scalars(select(AgentMemoryORM).where(
        AgentMemoryORM.user_id == user.id,
    ).order_by(AgentMemoryORM.created_at)).all()
    revisions = db.scalars(select(NewsletterItemRevisionORM).where(NewsletterItemRevisionORM.user_id == user.id)).all()
    llm_calls = db.scalars(select(LlmCallORM).where(LlmCallORM.user_id == user.id)).all()
    steps = db.scalars(select(AgentStepORM).where(AgentStepORM.user_id == user.id)).all()
    retrievals = db.scalars(select(RetrievalEventORM).where(RetrievalEventORM.user_id == user.id)).all()
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": MeRead.model_validate(user, from_attributes=True).model_dump(mode="json"),
        "captures": [CaptureRead.model_validate(row, from_attributes=True).model_dump(mode="json") for row in captures],
        "newsletters": [_newsletter_read(row, db).model_dump(mode="json") for row in newsletters],
        "feedback": [_feedback_read(row).model_dump(mode="json") for row in feedback],
        "memories": [_memory_read(row).model_dump(mode="json") for row in memories],
        "revisions": [{"id": row.id, "newsletter_id": row.newsletter_id, "capture_id": row.capture_id,
                       "version": row.version, "status": row.status, "content": row.content_json} for row in revisions],
        "telemetry": {
            "llm_calls": [{"id": row.id, "job_id": row.job_id, "purpose": row.purpose,
                           "model": row.model_name, "tokens": row.total_tokens, "cost_usd": row.estimated_cost_usd,
                           "status": row.status, "created_at": row.created_at.isoformat()} for row in llm_calls],
            "agent_steps": [{"id": row.id, "job_id": row.job_id, "step": row.step_name,
                             "status": row.status, "created_at": row.started_at.isoformat()} for row in steps],
            "retrieval_events": [{"id": row.id, "job_id": row.job_id, "provider": row.provider,
                                  "status": row.status, "created_at": row.created_at.isoformat()} for row in retrievals],
        },
    }


@router.delete("/me", status_code=204)
def delete_account(
    user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db),
) -> Response:
    row = db.get(UserORM, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")
    db.delete(row)
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie(auth.SESSION_COOKIE)
    return response


@router.post("/captures", response_model=CaptureRead, status_code=201)
def create_capture(
    body: PublicCaptureCreate,
    response: Response,
    user: UserORM = Depends(auth.current_user),
    db: Session = Depends(get_db),
) -> CaptureRead:
    existing = db.scalar(select(IdempotencyKeyORM).where(
        IdempotencyKeyORM.user_id == user.id, IdempotencyKeyORM.key == body.idempotency_key
    ))
    if existing:
        response.status_code = 200
        return CaptureRead.model_validate(db.get(CaptureORM, existing.capture_id), from_attributes=True)
    if not (body.url or body.selected_text or body.user_note):
        raise HTTPException(status_code=422, detail="Capture content is required")
    try:
        source_type = SourceType(body.source_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unsupported source_type") from exc
    capture = CaptureORM(
        id=str(uuid.uuid4()), user_id=user.id, source_type=source_type,
        url=body.url, title=body.title, selected_text=body.selected_text,
        user_note=body.user_note, domain=body.domain, description=body.description,
        author=body.author, captured_at=body.captured_at or datetime.now(timezone.utc),
        label=CaptureLabel.return_ if body.mode.value == "research" else CaptureLabel.casual,
    )
    db.add(capture)
    db.flush()
    db.add(IdempotencyKeyORM(
        id=str(uuid.uuid4()), user_id=user.id, key=body.idempotency_key, capture_id=capture.id
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(IdempotencyKeyORM).where(
            IdempotencyKeyORM.user_id == user.id, IdempotencyKeyORM.key == body.idempotency_key
        ))
        if not existing:
            raise
        response.status_code = 200
        capture = db.get(CaptureORM, existing.capture_id)
    db.refresh(capture)
    return CaptureRead.model_validate(capture, from_attributes=True)


@router.get("/captures", response_model=list[CaptureRead])
def list_captures(
    user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db)
) -> list[CaptureRead]:
    rows = db.scalars(select(CaptureORM).where(CaptureORM.user_id == user.id).order_by(CaptureORM.created_at.desc())).all()
    return [CaptureRead.model_validate(row, from_attributes=True) for row in rows]


@router.delete("/captures", status_code=204)
def clear_captures(
    user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db)
) -> Response:
    """Clear the current user's captures and derived newsletter issues."""
    active_job = db.scalar(select(JobORM.id).where(
        JobORM.user_id == user.id,
        JobORM.status.in_([JobStatus.queued, JobStatus.running]),
    ))
    if active_job:
        raise HTTPException(status_code=409, detail="Wait for newsletter generation to finish before clearing captures")
    db.execute(delete(NewsletterORM).where(NewsletterORM.user_id == user.id))
    db.execute(delete(CaptureORM).where(CaptureORM.user_id == user.id))
    db.commit()
    return Response(status_code=204)


@router.get("/cards", response_model=list[RevisitCardRead])
def list_cards(
    user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db)
) -> list[RevisitCardRead]:
    rows = db.scalars(select(RevisitCardORM).where(RevisitCardORM.user_id == user.id).order_by(RevisitCardORM.created_at.desc())).all()
    return [RevisitCardRead(
        **{k: v for k, v in row.__dict__.items() if not k.startswith("_")},
        resources=[r.model_dump() for r in resource_store.list_resources_for_card(db, row.id)],
    ) for row in rows]


def _newsletter_read(row: NewsletterORM, db: Session) -> NewsletterRead:
    revisions = db.scalars(select(NewsletterItemRevisionORM).where(
        NewsletterItemRevisionORM.newsletter_id == row.id,
    ).order_by(NewsletterItemRevisionORM.capture_id, NewsletterItemRevisionORM.version)).all()
    by_capture: dict[str, list[NewsletterItemRevisionORM]] = {}
    for revision in revisions:
        by_capture.setdefault(revision.capture_id, []).append(revision)
    items = []
    for original in row.items_json:
        item = dict(original)
        history = by_capture.get(item.get("capture_id"), [])
        succeeded = [revision for revision in history if revision.status == "succeeded" and revision.content_json]
        if succeeded:
            latest = succeeded[-1]
            item.update(latest.content_json)
            item["revision_id"] = latest.id
            item["revision_version"] = latest.version
        item["revision_history"] = [
            {"id": revision.id, "version": revision.version, "status": revision.status,
             "created_at": revision.created_at.isoformat()} for revision in history
        ]
        items.append(item)
    return NewsletterRead(
        id=row.id, subject=row.subject, introduction=row.introduction,
        items=items, created_at=row.created_at,
    )


@router.get("/newsletters", response_model=list[NewsletterRead])
def list_newsletters(
    user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db)
) -> list[NewsletterRead]:
    rows = db.scalars(select(NewsletterORM).where(
        NewsletterORM.user_id == user.id
    ).order_by(NewsletterORM.created_at.desc())).all()
    return [_newsletter_read(row, db) for row in rows]


@router.get("/newsletters/{newsletter_id}", response_model=NewsletterRead)
def get_newsletter(
    newsletter_id: str, user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db)
) -> NewsletterRead:
    row = db.scalar(select(NewsletterORM).where(
        NewsletterORM.id == newsletter_id, NewsletterORM.user_id == user.id
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="Newsletter not found")
    return _newsletter_read(row, db)


def _feedback_read(row: NewsletterFeedbackORM) -> NewsletterFeedbackRead:
    return NewsletterFeedbackRead(
        id=row.id, newsletter_id=row.newsletter_id, capture_id=row.capture_id,
        level=row.level, sentiment=row.sentiment, comment=row.comment, created_at=row.created_at,
    )


def _owned_newsletter(db: Session, newsletter_id: str, user_id: str) -> NewsletterORM:
    row = db.scalar(select(NewsletterORM).where(
        NewsletterORM.id == newsletter_id, NewsletterORM.user_id == user_id,
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="Newsletter not found")
    return row


def _duplicate_feedback(
    db: Session, *, user_id: str, newsletter_id: str, capture_id: str | None,
    sentiment: str, comment: str | None,
) -> NewsletterFeedbackORM | None:
    return db.scalar(select(NewsletterFeedbackORM).where(
        NewsletterFeedbackORM.user_id == user_id,
        NewsletterFeedbackORM.newsletter_id == newsletter_id,
        NewsletterFeedbackORM.capture_id.is_(None) if capture_id is None
        else NewsletterFeedbackORM.capture_id == capture_id,
        NewsletterFeedbackORM.sentiment == sentiment,
        func.coalesce(NewsletterFeedbackORM.comment, "") == (comment or ""),
    ).order_by(NewsletterFeedbackORM.created_at.desc()))


@router.post("/newsletters/{newsletter_id}/feedback", response_model=NewsletterFeedbackRead, status_code=201)
def create_newsletter_feedback(
    newsletter_id: str, body: NewsletterFeedbackCreate, background_tasks: BackgroundTasks,
    user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db),
) -> NewsletterFeedbackRead:
    _owned_newsletter(db, newsletter_id, user.id)
    comment = (body.comment or "").strip() or None
    existing = _duplicate_feedback(
        db, user_id=user.id, newsletter_id=newsletter_id, capture_id=None,
        sentiment=body.sentiment, comment=comment,
    )
    if existing:
        return _feedback_read(existing)
    row = NewsletterFeedbackORM(
        id=str(uuid.uuid4()), user_id=user.id, newsletter_id=newsletter_id,
        level="newsletter", sentiment=body.sentiment, comment=comment,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    background_tasks.add_task(memory_service.process_feedback_memory, row.id, user.id)
    return _feedback_read(row)


@router.post("/newsletters/{newsletter_id}/items/{capture_id}/feedback", response_model=NewsletterFeedbackRead, status_code=201)
def create_item_feedback(
    newsletter_id: str, capture_id: str, body: NewsletterFeedbackCreate,
    background_tasks: BackgroundTasks, user: UserORM = Depends(auth.current_user),
    db: Session = Depends(get_db),
) -> NewsletterFeedbackRead:
    newsletter = _owned_newsletter(db, newsletter_id, user.id)
    if not any(item.get("capture_id") == capture_id for item in newsletter.items_json):
        raise HTTPException(status_code=404, detail="Newsletter item not found")
    comment = (body.comment or "").strip() or None
    existing = _duplicate_feedback(
        db, user_id=user.id, newsletter_id=newsletter_id, capture_id=capture_id,
        sentiment=body.sentiment, comment=comment,
    )
    if existing:
        return _feedback_read(existing)
    row = NewsletterFeedbackORM(
        id=str(uuid.uuid4()), user_id=user.id, newsletter_id=newsletter_id,
        capture_id=capture_id, level="item", sentiment=body.sentiment,
        comment=comment,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    background_tasks.add_task(memory_service.process_feedback_memory, row.id, user.id)
    return _feedback_read(row)


@router.post("/newsletters/{newsletter_id}/items/{capture_id}/retry", response_model=JobRead, status_code=202)
def retry_newsletter_item(
    newsletter_id: str, capture_id: str, background_tasks: BackgroundTasks,
    user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db),
) -> JobRead:
    if os.environ.get("NEWSLETTER_REVISIONS_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="Not found")
    newsletter = _owned_newsletter(db, newsletter_id, user.id)
    if not any(item.get("capture_id") == capture_id for item in newsletter.items_json):
        raise HTTPException(status_code=404, detail="Newsletter item not found")
    feedback = db.scalar(select(NewsletterFeedbackORM).where(
        NewsletterFeedbackORM.user_id == user.id,
        NewsletterFeedbackORM.newsletter_id == newsletter_id,
        NewsletterFeedbackORM.capture_id == capture_id,
        NewsletterFeedbackORM.sentiment == "not_useful",
    ).order_by(NewsletterFeedbackORM.created_at.desc()))
    if feedback is None:
        raise HTTPException(status_code=409, detail="Add not-useful feedback before trying again")
    active = db.scalar(select(NewsletterItemRevisionORM).where(
        NewsletterItemRevisionORM.newsletter_id == newsletter_id,
        NewsletterItemRevisionORM.capture_id == capture_id,
        NewsletterItemRevisionORM.status.in_(["queued", "running"]),
    ))
    if active:
        return JobRead.model_validate(db.get(JobORM, active.job_id), from_attributes=True)
    version = int(db.scalar(select(func.max(NewsletterItemRevisionORM.version)).where(
        NewsletterItemRevisionORM.newsletter_id == newsletter_id,
        NewsletterItemRevisionORM.capture_id == capture_id,
    )) or 0) + 1
    job = JobORM(
        id=str(uuid.uuid4()), user_id=user.id, job_type=JobType.item_revision,
        status=JobStatus.queued, summary_json={},
    )
    revision = NewsletterItemRevisionORM(
        id=str(uuid.uuid4()), user_id=user.id, newsletter_id=newsletter_id,
        capture_id=capture_id, feedback_id=feedback.id, job_id=job.id,
        version=version, status="queued",
    )
    job.summary_json = {"revision_id": revision.id}
    db.add_all([job, revision])
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A retry is already running") from exc
    db.refresh(job)
    if os.environ.get("INLINE_RESEARCH_JOBS", "false").lower() == "true":
        background_tasks.add_task(run_inline_revision_job, job.id, revision.id, user.id)
    return JobRead.model_validate(job, from_attributes=True)


def _memory_read(row: AgentMemoryORM) -> MemoryRead:
    return MemoryRead(
        id=row.id, memory_type=row.memory_type, canonical_key=row.canonical_key,
        summary=row.summary, value=row.value_json, confidence=row.confidence,
        status=row.status, provenance_type=row.provenance_type,
        source_links=row.source_links_json, version=row.version,
        observed_at=row.observed_at, stale_at=row.stale_at, last_used_at=row.last_used_at,
        created_at=row.created_at, updated_at=row.updated_at,
    )


@router.get("/memories", response_model=list[MemoryRead])
def list_memories(
    user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db),
) -> list[MemoryRead]:
    return [_memory_read(row) for row in memory_service.list_memories(db, user.id)]


@router.patch("/memories/{memory_id}", response_model=MemoryRead)
def update_memory(
    memory_id: str, body: MemoryUpdate, user: UserORM = Depends(auth.current_user),
    db: Session = Depends(get_db),
) -> MemoryRead:
    row = db.scalar(select(AgentMemoryORM).where(
        AgentMemoryORM.id == memory_id, AgentMemoryORM.user_id == user.id,
        AgentMemoryORM.status.in_(["active", "disabled"]),
    ))
    if row is None or row.memory_type == "episodic":
        raise HTTPException(status_code=404, detail="Editable memory not found")
    updated = memory_service.revise_memory(
        db, row, summary=body.summary, value=body.value, status=body.status,
    )
    db.commit()
    db.refresh(updated)
    return _memory_read(updated)


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(
    memory_id: str, user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db),
) -> Response:
    row = db.scalar(select(AgentMemoryORM).where(
        AgentMemoryORM.id == memory_id, AgentMemoryORM.user_id == user.id,
        AgentMemoryORM.status.in_(["active", "disabled"]),
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    memory_service.forget_memory(db, row)
    db.commit()
    return Response(status_code=204)


@router.delete("/memories", status_code=204)
def reset_memories(
    user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db),
) -> Response:
    memory_service.reset_memories(db, user.id)
    db.commit()
    return Response(status_code=204)


@router.post("/jobs/research", response_model=JobRead, status_code=202)
def enqueue_research(
    background_tasks: BackgroundTasks,
    user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db)
) -> JobRead:
    active = db.scalar(select(JobORM).where(
        JobORM.user_id == user.id, JobORM.status.in_([JobStatus.queued, JobStatus.running])
    ))
    if active:
        if os.environ.get("INLINE_RESEARCH_JOBS", "false").lower() == "true" and active.status == JobStatus.queued:
            background_tasks.add_task(run_inline_research_job, active.id, user.id)
        return JobRead.model_validate(active, from_attributes=True)
    row = JobORM(id=str(uuid.uuid4()), user_id=user.id, job_type=JobType.daily_batch, status=JobStatus.queued)
    db.add(row)
    db.commit()
    db.refresh(row)
    if os.environ.get("INLINE_RESEARCH_JOBS", "false").lower() == "true":
        background_tasks.add_task(run_inline_research_job, row.id, user.id)
    return JobRead.model_validate(row, from_attributes=True)


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(
    job_id: str, user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db)
) -> JobRead:
    row = db.scalar(select(JobORM).where(JobORM.id == job_id, JobORM.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobRead.model_validate(row, from_attributes=True)


@router.get("/auth/google/login")
def google_web_login() -> RedirectResponse:
    client_id = os.environ.get("GOOGLE_WEB_CLIENT_ID")
    redirect_uri = os.environ.get("GOOGLE_WEB_REDIRECT_URI")
    if not client_id or not redirect_uri:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    state = secrets.token_urlsafe(32)
    params = urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": "openid email profile", "state": state, "access_type": "online",
    })
    response = RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")
    response.set_cookie("revisit_oauth_state", state, httponly=True, secure=os.environ.get("ENVIRONMENT") == "production", samesite="lax", max_age=600)
    return response


@router.get("/auth/google/callback")
def google_web_callback(request: Request, code: str, state: str) -> RedirectResponse:
    if not secrets.compare_digest(state, request.cookies.get("revisit_oauth_state", "")):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    try:
        token_response = requests.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": os.environ["GOOGLE_WEB_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_WEB_CLIENT_SECRET"],
            "redirect_uri": os.environ["GOOGLE_WEB_REDIRECT_URI"], "grant_type": "authorization_code",
        }, timeout=10)
        token_response.raise_for_status()
        token_data = token_response.json()
        id_info_response = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": token_data["id_token"]}, timeout=10,
        )
        id_info_response.raise_for_status()
        id_info = id_info_response.json()
        if id_info.get("aud") != os.environ["GOOGLE_WEB_CLIENT_ID"] or id_info.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
            raise ValueError("Invalid Google ID token")
        profile = id_info
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Google sign-in failed") from exc
    user = auth.upsert_google_user(profile)
    session = auth.create_session(user.id)
    response = RedirectResponse("/app/backlog", status_code=302)
    response.set_cookie(auth.SESSION_COOKIE, session, httponly=True, secure=os.environ.get("ENVIRONMENT") == "production", samesite="lax", max_age=auth.SESSION_TTL_SECONDS)
    response.delete_cookie("revisit_oauth_state")
    return response
