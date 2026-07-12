"""create capture_embeddings table

Revision ID: 79955ad85405
Revises: beed6164934a
Create Date: 2026-06-23 18:55:34.363656

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


# revision identifiers, used by Alembic.
revision: str = '79955ad85405'
down_revision: Union[str, Sequence[str], None] = 'beed6164934a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table('capture_embeddings',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('capture_id', sa.String(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.Vector(dim=1536), nullable=False),
    sa.Column('embedding_model', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['capture_id'], ['captures.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('capture_id')
    )

    # HNSW index for approximate cosine-similarity search (pgvector >= 0.5.0)
    op.execute(
        "CREATE INDEX capture_embeddings_embedding_idx "
        "ON capture_embeddings USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS capture_embeddings_embedding_idx")
    op.drop_table('capture_embeddings')
