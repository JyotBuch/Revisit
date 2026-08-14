"""add anonymous telemetry rollups

Revision ID: e8f6b2d5c031
Revises: d7e5a1c4b920
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e8f6b2d5c031"
down_revision: Union[str, None] = "d7e5a1c4b920"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telemetry_daily_aggregates",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute(
        "CREATE INDEX agent_memories_embedding_idx ON agent_memories "
        "USING hnsw (embedding vector_cosine_ops) WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS agent_memories_embedding_idx")
    op.drop_table("telemetry_daily_aggregates")
