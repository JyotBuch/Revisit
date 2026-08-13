from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_auth, require_legacy_pipeline_disabled_in_production
from app.models.user import UserORM
from app.db import get_db
from app.schemas.capture import CaptureCreate, CaptureRead
from app.schemas.embedding import CaptureEmbeddingRead, SimilarCapture
from app.services import capture_store, embeddings, extraction

router = APIRouter(prefix="/captures", tags=["captures"])


@router.post("", response_model=CaptureRead, status_code=201)
def create_capture(
    data: CaptureCreate,
    db: Session = Depends(get_db),
    user: UserORM | None = Depends(require_auth),
) -> CaptureRead:
    capture = capture_store.create_capture(db, data, user_id=user.id if user else None)
    return CaptureRead(**capture.model_dump())


@router.get("", response_model=list[CaptureRead])
def list_captures(db: Session = Depends(get_db), user: UserORM | None = Depends(require_auth)) -> list[CaptureRead]:
    return [CaptureRead(**c.model_dump()) for c in capture_store.list_captures(db, user_id=user.id if user else None)]


@router.get("/{capture_id}", response_model=CaptureRead)
def get_capture(capture_id: str, db: Session = Depends(get_db), user: UserORM | None = Depends(require_auth)) -> CaptureRead:
    capture = capture_store.get_capture(db, capture_id, user_id=user.id if user else None)
    if capture is None:
        raise HTTPException(status_code=404, detail="Capture not found")
    return CaptureRead(**capture.model_dump())


@router.post("/{capture_id}/extract", response_model=CaptureRead)
def extract_capture(
    capture_id: str,
    db: Session = Depends(get_db),
    user: UserORM | None = Depends(require_auth),
) -> CaptureRead:
    require_legacy_pipeline_disabled_in_production()
    capture = capture_store.get_capture(db, capture_id, user_id=user.id if user else None)
    if capture is None:
        raise HTTPException(status_code=404, detail="Capture not found")

    result = extraction.extract_capture_content(capture)
    updated = capture_store.update_extraction(
        db,
        capture_id,
        extracted_text=result.extracted_text,
        status=result.status,
        extraction_error=result.extraction_error,
    )
    return CaptureRead(**updated.model_dump())


@router.post("/{capture_id}/embed", response_model=CaptureEmbeddingRead, status_code=201)
def embed_capture(
    capture_id: str,
    db: Session = Depends(get_db),
    user: UserORM | None = Depends(require_auth),
) -> CaptureEmbeddingRead:
    require_legacy_pipeline_disabled_in_production()
    capture = capture_store.get_capture(db, capture_id, user_id=user.id if user else None)
    if capture is None:
        raise HTTPException(status_code=404, detail="Capture not found")
    if not capture.extracted_text:
        raise HTTPException(
            status_code=400,
            detail="Capture has no extracted_text; run extraction first",
        )

    row = embeddings.create_embedding_for_capture(db, capture_id)
    return CaptureEmbeddingRead(
        id=row.id,
        capture_id=row.capture_id,
        embedding_model=row.embedding_model,
        created_at=row.created_at,
    )


@router.get("/{capture_id}/similar", response_model=list[SimilarCapture])
def similar_captures(
    capture_id: str,
    limit: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
    user: UserORM | None = Depends(require_auth),
) -> list[SimilarCapture]:
    require_legacy_pipeline_disabled_in_production()
    capture = capture_store.get_capture(db, capture_id, user_id=user.id if user else None)
    if capture is None:
        raise HTTPException(status_code=404, detail="Capture not found")

    results = embeddings.find_similar_captures(db, capture_id, limit=limit)
    if results is None:
        raise HTTPException(
            status_code=400,
            detail="Capture has no embedding; call /embed first",
        )

    return [
        SimilarCapture(capture=CaptureRead(**c.model_dump()), similarity=similarity)
        for c, similarity in results
    ]
