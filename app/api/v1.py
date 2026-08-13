import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import auth
from app.db import get_db
from app.models.capture import CaptureORM
from app.models.job import JobORM
from app.models.newsletter import NewsletterORM
from app.models.revisit_card import RevisitCardORM
from app.models.user import ExtensionTokenORM, IdempotencyKeyORM, UserORM
from app.schemas.account import (
    ExtensionGoogleLogin, ExtensionTokenRead, MeRead, MeUpdate, PublicCaptureCreate,
)
from app.schemas.capture import CaptureLabel, CaptureRead, SourceType
from app.schemas.job import JobRead, JobStatus, JobType
from app.schemas.newsletter import NewsletterRead
from app.schemas.revisit_card import RevisitCardRead
from app.services import resource_store

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


@router.get("/cards", response_model=list[RevisitCardRead])
def list_cards(
    user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db)
) -> list[RevisitCardRead]:
    rows = db.scalars(select(RevisitCardORM).where(RevisitCardORM.user_id == user.id).order_by(RevisitCardORM.created_at.desc())).all()
    return [RevisitCardRead(
        **{k: v for k, v in row.__dict__.items() if not k.startswith("_")},
        resources=[r.model_dump() for r in resource_store.list_resources_for_card(db, row.id)],
    ) for row in rows]


def _newsletter_read(row: NewsletterORM) -> NewsletterRead:
    return NewsletterRead(
        id=row.id, subject=row.subject, introduction=row.introduction,
        items=row.items_json, created_at=row.created_at,
    )


@router.get("/newsletters", response_model=list[NewsletterRead])
def list_newsletters(
    user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db)
) -> list[NewsletterRead]:
    rows = db.scalars(select(NewsletterORM).where(
        NewsletterORM.user_id == user.id
    ).order_by(NewsletterORM.created_at.desc())).all()
    return [_newsletter_read(row) for row in rows]


@router.get("/newsletters/{newsletter_id}", response_model=NewsletterRead)
def get_newsletter(
    newsletter_id: str, user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db)
) -> NewsletterRead:
    row = db.scalar(select(NewsletterORM).where(
        NewsletterORM.id == newsletter_id, NewsletterORM.user_id == user.id
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="Newsletter not found")
    return _newsletter_read(row)


@router.post("/jobs/research", response_model=JobRead, status_code=202)
def enqueue_research(
    user: UserORM = Depends(auth.current_user), db: Session = Depends(get_db)
) -> JobRead:
    active = db.scalar(select(JobORM).where(
        JobORM.user_id == user.id, JobORM.status.in_([JobStatus.queued, JobStatus.running])
    ))
    if active:
        return JobRead.model_validate(active, from_attributes=True)
    row = JobORM(id=str(uuid.uuid4()), user_id=user.id, job_type=JobType.daily_batch, status=JobStatus.queued)
    db.add(row)
    db.commit()
    db.refresh(row)
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
