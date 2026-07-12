from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db import get_db
from app.schemas.resource import ResourceRead
from app.schemas.revisit_card import GenerationMethod, RevisitCard, RevisitCardRead
from app.services import capture_store, clustering, resource_store, revisit_card_store

router = APIRouter(tags=["revisit-cards"])


def _to_card_read(db: Session, card: RevisitCard) -> RevisitCardRead:
    resources = resource_store.list_resources_for_card(db, card.id)
    return RevisitCardRead(
        **card.model_dump(),
        resources=[ResourceRead(**r.model_dump()) for r in resources],
    )


@router.post(
    "/captures/{capture_id}/revisit-card",
    response_model=RevisitCardRead,
    status_code=201,
)
def create_revisit_card(
    capture_id: str,
    generation_method: GenerationMethod = Query(default=GenerationMethod.rule_based),
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
) -> RevisitCardRead:
    capture = capture_store.get_capture(db, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail="Capture not found")
    card = revisit_card_store.create_revisit_card_for_capture(
        db, capture, generation_method=generation_method
    )
    return _to_card_read(db, card)


@router.post(
    "/clusters/{cluster_id}/revisit-card",
    response_model=RevisitCardRead,
    status_code=201,
)
def create_cluster_revisit_card(
    cluster_id: str,
    generation_method: GenerationMethod = Query(default=GenerationMethod.rule_based),
    include_resources: bool = Query(default=True),
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
) -> RevisitCardRead:
    cluster = clustering.get_cluster(db, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    if not cluster.items:
        raise HTTPException(status_code=400, detail="Cluster has no captures")

    card = revisit_card_store.create_revisit_card_for_cluster(
        db, cluster, generation_method=generation_method, include_resources=include_resources
    )
    return _to_card_read(db, card)


@router.get("/revisit-cards", response_model=list[RevisitCardRead])
def list_revisit_cards(db: Session = Depends(get_db)) -> list[RevisitCardRead]:
    return [_to_card_read(db, c) for c in revisit_card_store.list_revisit_cards(db)]


@router.get("/revisit-cards/{card_id}", response_model=RevisitCardRead)
def get_revisit_card(card_id: str, db: Session = Depends(get_db)) -> RevisitCardRead:
    card = revisit_card_store.get_revisit_card(db, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Revisit Card not found")
    return _to_card_read(db, card)
