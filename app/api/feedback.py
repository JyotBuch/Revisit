from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db import get_db
from app.schemas.feedback import (
    FeedbackSummary,
    RevisitCardFeedbackCreate,
    RevisitCardFeedbackRead,
)
from app.services import feedback_store, revisit_card_store

router = APIRouter(tags=["feedback"])


@router.post(
    "/revisit-cards/{card_id}/feedback",
    response_model=RevisitCardFeedbackRead,
    status_code=201,
)
def create_feedback(
    card_id: str,
    feedback: RevisitCardFeedbackCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
) -> RevisitCardFeedbackRead:
    card = revisit_card_store.get_revisit_card(db, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Revisit Card not found")

    created = feedback_store.create_feedback(db, card_id, feedback)
    return RevisitCardFeedbackRead(**created.model_dump())


@router.get(
    "/revisit-cards/{card_id}/feedback",
    response_model=list[RevisitCardFeedbackRead],
)
def list_feedback(card_id: str, db: Session = Depends(get_db)) -> list[RevisitCardFeedbackRead]:
    card = revisit_card_store.get_revisit_card(db, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Revisit Card not found")

    return [
        RevisitCardFeedbackRead(**f.model_dump())
        for f in feedback_store.list_feedback_for_card(db, card_id)
    ]


@router.get("/feedback/summary", response_model=FeedbackSummary)
def feedback_summary(db: Session = Depends(get_db)) -> FeedbackSummary:
    return FeedbackSummary(**feedback_store.summarize_feedback(db))
