from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.resource import ResourceORM
    from app.models.revisit_card import RevisitCardORM


class RevisitCardResourceORM(Base):
    __tablename__ = "revisit_card_resources"
    __table_args__ = (
        UniqueConstraint(
            "revisit_card_id", "resource_id", name="uq_revisit_card_resources_card_resource"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    revisit_card_id: Mapped[str] = mapped_column(
        String, ForeignKey("revisit_cards.id"), nullable=False
    )
    resource_id: Mapped[str] = mapped_column(
        String, ForeignKey("resources.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    revisit_card: Mapped["RevisitCardORM"] = relationship(back_populates="resource_links")
    resource: Mapped["ResourceORM"] = relationship()
