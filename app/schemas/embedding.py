from datetime import datetime

from pydantic import BaseModel

from app.schemas.capture import CaptureRead


class CaptureEmbeddingRead(BaseModel):
    id: str
    capture_id: str
    embedding_model: str
    created_at: datetime


class SimilarCapture(BaseModel):
    capture: CaptureRead
    similarity: float
