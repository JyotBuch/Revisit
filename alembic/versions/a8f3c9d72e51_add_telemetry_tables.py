"""add telemetry tables

Revision ID: a8f3c9d72e51
Revises: 5607f612754a
Create Date: 2026-07-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a8f3c9d72e51'
down_revision: Union[str, Sequence[str], None] = '3058b529bc33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'llm_calls',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=True),
        sa.Column('owner_type', sa.String(), nullable=True),
        sa.Column('owner_id', sa.String(), nullable=True),
        sa.Column('purpose', sa.String(), nullable=False),
        sa.Column('model_name', sa.String(), nullable=False),
        sa.Column('prompt_version', sa.String(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('estimated_cost_usd', sa.Float(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('failure_type', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_llm_calls_job_id', 'llm_calls', ['job_id'])

    op.create_table(
        'agent_steps',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=True),
        sa.Column('step_name', sa.String(), nullable=False),
        sa.Column('owner_type', sa.String(), nullable=True),
        sa.Column('owner_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('input_summary_json', sa.JSON(), nullable=True),
        sa.Column('output_summary_json', sa.JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agent_steps_job_id', 'agent_steps', ['job_id'])

    op.create_table(
        'retrieval_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=True),
        sa.Column('cluster_id', sa.String(), nullable=True),
        sa.Column('query', sa.String(), nullable=True),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('num_candidates', sa.Integer(), nullable=True),
        sa.Column('num_accepted', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_retrieval_events_job_id', 'retrieval_events', ['job_id'])


def downgrade() -> None:
    op.drop_index('ix_retrieval_events_job_id', 'retrieval_events')
    op.drop_table('retrieval_events')
    op.drop_index('ix_agent_steps_job_id', 'agent_steps')
    op.drop_table('agent_steps')
    op.drop_index('ix_llm_calls_job_id', 'llm_calls')
    op.drop_table('llm_calls')
