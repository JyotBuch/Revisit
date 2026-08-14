"""add agent memory, newsletter feedback, revisions, and production telemetry

Revision ID: d7e5a1c4b920
Revises: c4b8f2a1d901
"""

from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa

revision: str = "d7e5a1c4b920"
down_revision: Union[str, None] = "c4b8f2a1d901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'item_revision'")
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("memory_type", sa.String(), nullable=False),
        sa.Column("canonical_key", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("provenance_type", sa.String(), nullable=False),
        sa.Column("provenance_id", sa.String(), nullable=True),
        sa.Column("source_links_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=1536), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("memory_type IN ('procedural', 'semantic', 'episodic')", name="ck_agent_memory_type"),
        sa.CheckConstraint("status IN ('active', 'disabled', 'superseded', 'deleted')", name="ck_agent_memory_status"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_agent_memory_confidence"),
        sa.UniqueConstraint("user_id", "canonical_key", "version", name="uq_agent_memory_user_key_version"),
    )
    op.create_index("ix_agent_memories_user_id", "agent_memories", ["user_id"])
    op.create_index("ix_agent_memories_memory_type", "agent_memories", ["memory_type"])
    op.create_index("ix_agent_memories_status", "agent_memories", ["status"])

    op.create_table(
        "newsletter_feedback",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("newsletter_id", sa.String(), sa.ForeignKey("newsletters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capture_id", sa.String(), sa.ForeignKey("captures.id", ondelete="CASCADE"), nullable=True),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("sentiment", sa.String(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("memory_processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("level IN ('newsletter', 'item')", name="ck_newsletter_feedback_level"),
        sa.CheckConstraint("sentiment IN ('useful', 'not_useful')", name="ck_newsletter_feedback_sentiment"),
    )
    op.create_index("ix_newsletter_feedback_user_id", "newsletter_feedback", ["user_id"])
    op.create_index("ix_newsletter_feedback_newsletter_id", "newsletter_feedback", ["newsletter_id"])

    op.create_table(
        "newsletter_item_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("newsletter_id", sa.String(), sa.ForeignKey("newsletters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capture_id", sa.String(), sa.ForeignKey("captures.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feedback_id", sa.String(), sa.ForeignKey("newsletter_feedback.id", ondelete="SET NULL"), nullable=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("content_json", sa.JSON(), nullable=True),
        sa.Column("memory_ids_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_newsletter_item_revision_status"),
        sa.UniqueConstraint("newsletter_id", "capture_id", "version", name="uq_newsletter_item_revision_version"),
    )
    op.create_index("ix_newsletter_item_revisions_user_id", "newsletter_item_revisions", ["user_id"])
    op.create_index("ix_newsletter_item_revisions_newsletter_id", "newsletter_item_revisions", ["newsletter_id"])
    op.create_index(
        "uq_newsletter_item_revision_active", "newsletter_item_revisions", ["newsletter_id", "capture_id"],
        unique=True, postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    for table in ("llm_calls", "agent_steps", "retrieval_events"):
        op.add_column(table, sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index(f"ix_{table}_expires_at", table, ["expires_at"])
    for name in ("provider_request_id", "finish_reason", "request_hash", "response_hash"):
        op.add_column("llm_calls", sa.Column(name, sa.String(), nullable=True))
    op.add_column("llm_calls", sa.Column("response_excerpt", sa.Text(), nullable=True))
    for name in ("owner_type", "owner_id", "query_hash", "query_intent"):
        op.add_column("retrieval_events", sa.Column(name, sa.String(), nullable=True))
    op.add_column("retrieval_events", sa.Column("accepted_ids_json", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("retrieval_events", sa.Column("memory_ids_json", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("retrieval_events", sa.Column("memory_scores_json", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    for name in ("memory_scores_json", "memory_ids_json", "accepted_ids_json", "query_intent", "query_hash", "owner_id", "owner_type"):
        op.drop_column("retrieval_events", name)
    for name in ("response_excerpt", "response_hash", "request_hash", "finish_reason", "provider_request_id"):
        op.drop_column("llm_calls", name)
    for table in ("retrieval_events", "agent_steps", "llm_calls"):
        op.drop_index(f"ix_{table}_expires_at", table_name=table)
        op.drop_column(table, "expires_at")
    op.drop_index("uq_newsletter_item_revision_active", table_name="newsletter_item_revisions")
    op.drop_table("newsletter_item_revisions")
    op.drop_table("newsletter_feedback")
    op.drop_table("agent_memories")
