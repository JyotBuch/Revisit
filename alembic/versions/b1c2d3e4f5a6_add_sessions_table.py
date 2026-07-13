"""add_sessions_table

Revision ID: b1c2d3e4f5a6
Revises: a8f3c9d72e51
Create Date: 2026-07-12 19:03:16.422249

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'a8f3c9d72e51'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sessions',
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('expires_at', sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint('token'),
    )
    op.create_index('ix_sessions_expires_at', 'sessions', ['expires_at'])


def downgrade() -> None:
    op.drop_index('ix_sessions_expires_at', table_name='sessions')
    op.drop_table('sessions')
