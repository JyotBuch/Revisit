"""add llm generation fields to revisit cards

Revision ID: 5607f612754a
Revises: 250e22df5fd7
Create Date: 2026-06-23 21:59:48.971254

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5607f612754a'
down_revision: Union[str, Sequence[str], None] = '250e22df5fd7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOTE: autogenerate also proposed dropping capture_embeddings_embedding_idx
    # (the HNSW index, created via raw SQL rather than a SQLAlchemy Index
    # object) here — same false positive as in prior migrations. That
    # op.drop_index() call has been removed; do not restore it.

    # op.add_column() does not auto-create the backing Postgres ENUM type
    # the way op.create_table() does, so it must be created explicitly first.
    generation_method_enum = sa.Enum('rule_based', 'llm', name='generation_method')
    generation_method_enum.create(op.get_bind(), checkfirst=True)
    op.add_column('revisit_cards', sa.Column('generation_method', generation_method_enum, server_default='rule_based', nullable=False))
    op.add_column('revisit_cards', sa.Column('model_name', sa.String(), nullable=True))
    op.add_column('revisit_cards', sa.Column('prompt_version', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('revisit_cards', 'prompt_version')
    op.drop_column('revisit_cards', 'model_name')
    op.drop_column('revisit_cards', 'generation_method')
    sa.Enum(name='generation_method').drop(op.get_bind(), checkfirst=True)
