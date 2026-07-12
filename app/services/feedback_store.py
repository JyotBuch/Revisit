import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.revisit_card_feedback import RevisitCardFeedbackORM
from app.schemas.feedback import (
    FeedbackAction,
    RevisitCardFeedback,
    RevisitCardFeedbackCreate,
)


def create_feedback(
    db: Session, revisit_card_id: str, feedback: RevisitCardFeedbackCreate
) -> RevisitCardFeedback:
    row = RevisitCardFeedbackORM(
        id=str(uuid.uuid4()),
        revisit_card_id=revisit_card_id,
        action=feedback.action,
        rating=feedback.rating,
        comment=feedback.comment,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return RevisitCardFeedback.model_validate(row, from_attributes=True)


def list_feedback_for_card(db: Session, revisit_card_id: str) -> List[RevisitCardFeedback]:
    rows = db.scalars(
        select(RevisitCardFeedbackORM)
        .where(RevisitCardFeedbackORM.revisit_card_id == revisit_card_id)
        .order_by(RevisitCardFeedbackORM.created_at)
    ).all()
    return [RevisitCardFeedback.model_validate(row, from_attributes=True) for row in rows]


def summarize_feedback(db: Session) -> Dict[str, Any]:
    total = db.scalar(select(func.count()).select_from(RevisitCardFeedbackORM)) or 0

    counts_by_action: Dict[str, int] = {action.value: 0 for action in FeedbackAction}
    rows = db.execute(
        select(RevisitCardFeedbackORM.action, func.count())
        .group_by(RevisitCardFeedbackORM.action)
    ).all()
    for action, count in rows:
        counts_by_action[action.value if hasattr(action, "value") else action] = count

    average_rating: Optional[float] = db.scalar(
        select(func.avg(RevisitCardFeedbackORM.rating)).where(
            RevisitCardFeedbackORM.rating.is_not(None)
        )
    )
    if average_rating is not None:
        average_rating = round(float(average_rating), 2)

    useful_count = counts_by_action.get(FeedbackAction.useful.value, 0)
    not_useful_count = counts_by_action.get(FeedbackAction.not_useful.value, 0)
    useful_denominator = useful_count + not_useful_count
    useful_rate = useful_count / useful_denominator if useful_denominator > 0 else None

    dismissed_count = counts_by_action.get(FeedbackAction.dismissed.value, 0)
    dismiss_rate = dismissed_count / total if total > 0 else None

    return {
        "total_feedback_events": total,
        "counts_by_action": counts_by_action,
        "average_rating": average_rating,
        "useful_rate": useful_rate,
        "dismiss_rate": dismiss_rate,
    }
