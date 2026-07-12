import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.capture import CaptureORM
from app.schemas.capture import Capture, CaptureCreate, CaptureStatus


def create_capture(db: Session, data: CaptureCreate) -> Capture:
    row = CaptureORM(id=str(uuid.uuid4()), **data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return Capture.model_validate(row, from_attributes=True)


def list_captures(db: Session) -> List[Capture]:
    rows = db.scalars(select(CaptureORM)).all()
    return [Capture.model_validate(row, from_attributes=True) for row in rows]


def get_capture(db: Session, capture_id: str) -> Optional[Capture]:
    row = db.get(CaptureORM, capture_id)
    if row is None:
        return None
    return Capture.model_validate(row, from_attributes=True)


def update_extraction(
    db: Session,
    capture_id: str,
    *,
    extracted_text: Optional[str],
    status: CaptureStatus,
    extraction_error: Optional[str],
) -> Optional[Capture]:
    row = db.get(CaptureORM, capture_id)
    if row is None:
        return None
    row.extracted_text = extracted_text
    row.status = status
    row.extraction_error = extraction_error
    db.commit()
    db.refresh(row)
    return Capture.model_validate(row, from_attributes=True)
