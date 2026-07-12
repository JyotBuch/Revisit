import hashlib
import os
import random
import uuid
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.capture import CaptureORM
from app.models.capture_embedding import EMBEDDING_DIM, CaptureEmbeddingORM
from app.schemas.capture import Capture

OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"

# Only for local development/testing when OPENAI_API_KEY isn't set. This is
# NOT a real embedding model — vectors are derived from a hash of the input
# text, so they only cluster on incidental string overlap, never on meaning.
FAKE_EMBEDDING_MODEL = "fake-local-dev-v1"


class NoExtractedTextError(Exception):
    pass


def _fake_embedding(text: str) -> List[float]:
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(EMBEDDING_DIM)]


def _openai_embedding(text: str) -> List[float]:
    from openai import OpenAI

    client = OpenAI()
    response = client.embeddings.create(model=OPENAI_EMBEDDING_MODEL, input=text)
    return response.data[0].embedding


def _active_embedding_model() -> str:
    return OPENAI_EMBEDDING_MODEL if os.environ.get("OPENAI_API_KEY") else FAKE_EMBEDDING_MODEL


def generate_embedding(text: str) -> List[float]:
    if os.environ.get("OPENAI_API_KEY"):
        return _openai_embedding(text)
    return _fake_embedding(text)


def get_embedding(db: Session, capture_id: str) -> Optional[CaptureEmbeddingORM]:
    return db.scalar(
        select(CaptureEmbeddingORM).where(CaptureEmbeddingORM.capture_id == capture_id)
    )


def create_embedding_for_capture(db: Session, capture_id: str) -> CaptureEmbeddingORM:
    capture = db.get(CaptureORM, capture_id)
    if capture is None:
        raise ValueError(f"Capture not found: {capture_id}")
    if not capture.extracted_text:
        raise NoExtractedTextError(
            "Capture has no extracted_text; run extraction first."
        )

    vector = generate_embedding(capture.extracted_text)
    model_name = _active_embedding_model()

    row = get_embedding(db, capture_id)
    if row is None:
        row = CaptureEmbeddingORM(id=str(uuid.uuid4()), capture_id=capture_id)
        db.add(row)
    row.embedding = vector
    row.embedding_model = model_name

    db.commit()
    db.refresh(row)
    return row


def find_similar_captures(
    db: Session, capture_id: str, limit: int = 5
) -> Optional[List[Tuple[Capture, float]]]:
    source = get_embedding(db, capture_id)
    if source is None:
        return None

    distance = CaptureEmbeddingORM.embedding.cosine_distance(source.embedding)
    rows = db.execute(
        select(CaptureORM, distance.label("distance"))
        .join(CaptureEmbeddingORM, CaptureEmbeddingORM.capture_id == CaptureORM.id)
        .where(CaptureEmbeddingORM.capture_id != capture_id)
        .order_by(distance)
        .limit(limit)
    ).all()

    return [
        (Capture.model_validate(capture_row, from_attributes=True), 1 - dist)
        for capture_row, dist in rows
    ]
