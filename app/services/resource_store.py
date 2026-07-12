import uuid
from typing import List, Set

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.resource import ResourceORM
from app.models.revisit_card_resource import RevisitCardResourceORM
from app.schemas.resource import Resource


def create_resource(db: Session, resource: Resource) -> Resource:
    row = ResourceORM(
        id=resource.id,
        cluster_id=resource.cluster_id,
        url=resource.url,
        title=resource.title,
        source_type=resource.source_type,
        snippet=resource.snippet,
        query=resource.query,
        relevance_score=resource.relevance_score,
        validation_score=resource.validation_score,
        validation_reason=resource.validation_reason,
        provider=resource.provider,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return Resource.model_validate(row, from_attributes=True)


def list_resources_for_cluster(db: Session, cluster_id: str) -> List[Resource]:
    rows = db.scalars(
        select(ResourceORM)
        .where(ResourceORM.cluster_id == cluster_id)
        .order_by(ResourceORM.created_at)
    ).all()
    return [Resource.model_validate(row, from_attributes=True) for row in rows]


def get_resource_urls_for_cluster(db: Session, cluster_id: str) -> Set[str]:
    rows = db.scalars(
        select(ResourceORM.url).where(ResourceORM.cluster_id == cluster_id)
    ).all()
    return set(rows)


def link_resource_to_card(db: Session, revisit_card_id: str, resource_id: str) -> None:
    row = RevisitCardResourceORM(
        id=str(uuid.uuid4()), revisit_card_id=revisit_card_id, resource_id=resource_id
    )
    db.add(row)
    db.commit()


def list_resources_for_card(db: Session, revisit_card_id: str) -> List[Resource]:
    rows = db.scalars(
        select(ResourceORM)
        .join(RevisitCardResourceORM, RevisitCardResourceORM.resource_id == ResourceORM.id)
        .where(RevisitCardResourceORM.revisit_card_id == revisit_card_id)
        .order_by(RevisitCardResourceORM.created_at)
    ).all()
    return [Resource.model_validate(row, from_attributes=True) for row in rows]
