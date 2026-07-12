"""add stable cluster identity fields

Revision ID: 3058b529bc33
Revises: f7369ee72e1a
Create Date: 2026-06-24 12:28:52.374223

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


# revision identifiers, used by Alembic.
revision: str = '3058b529bc33'
down_revision: Union[str, Sequence[str], None] = 'f7369ee72e1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOTE: autogenerate also proposed dropping capture_embeddings_embedding_idx
    # (the HNSW index, created via raw SQL rather than a SQLAlchemy Index
    # object) here — same false positive as in every prior migration that
    # touched another table. That op.drop_index() call has been removed;
    # do not restore it.
    op.add_column(
        'cluster_items',
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    )

    # op.add_column() does not auto-create the backing Postgres ENUM type
    # the way op.create_table() does, so it must be created explicitly first.
    cluster_status_enum = sa.Enum('active', 'archived', name='cluster_status')
    cluster_status_enum.create(op.get_bind(), checkfirst=True)

    op.add_column('clusters', sa.Column('representative_capture_id', sa.String(), nullable=True))
    op.add_column('clusters', sa.Column('centroid_embedding', pgvector.sqlalchemy.Vector(dim=1536), nullable=True))
    op.add_column('clusters', sa.Column('status', cluster_status_enum, server_default='active', nullable=False))
    op.add_column('clusters', sa.Column('last_clustered_at', sa.DateTime(), nullable=True))
    op.create_foreign_key(None, 'clusters', 'captures', ['representative_capture_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(None, 'clusters', type_='foreignkey')
    op.drop_column('clusters', 'last_clustered_at')
    op.drop_column('clusters', 'status')
    sa.Enum(name='cluster_status').drop(op.get_bind(), checkfirst=True)
    op.drop_column('clusters', 'centroid_embedding')
    op.drop_column('clusters', 'representative_capture_id')
    op.drop_column('cluster_items', 'updated_at')
