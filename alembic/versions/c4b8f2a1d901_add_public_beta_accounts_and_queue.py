"""add public beta accounts, ownership, capture metadata, and queue fields

Revision ID: c4b8f2a1d901
Revises: b1c2d3e4f5a6
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4b8f2a1d901"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'queued'")
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("google_sub", sa.String(), nullable=False, unique=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(), nullable=False, server_default="UTC"),
        sa.Column("nightly_research_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_nightly_run_date", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "extension_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False, server_default="Chrome extension"),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_extension_tokens_user_id", "extension_tokens", ["user_id"])
    op.create_index("ix_extension_tokens_token_hash", "extension_tokens", ["token_hash"], unique=True)
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("capture_id", sa.String(), sa.ForeignKey("captures.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "key", name="uq_idempotency_user_key"),
    )
    op.create_index("ix_idempotency_keys_user_id", "idempotency_keys", ["user_id"])
    op.add_column("sessions", sa.Column("user_id", sa.String(), nullable=True))
    op.add_column("sessions", sa.Column("csrf_token", sa.String(), nullable=True))
    op.create_foreign_key("fk_sessions_user_id", "sessions", "users", ["user_id"], ["id"], ondelete="CASCADE")

    for table in ["captures", "clusters", "revisit_cards", "resources", "revisit_card_feedback", "jobs", "llm_calls", "agent_steps", "retrieval_events"]:
        op.add_column(table, sa.Column("user_id", sa.String(), nullable=True))
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])
        op.create_foreign_key(f"fk_{table}_user_id", table, "users", ["user_id"], ["id"], ondelete="CASCADE")

    for name in ["domain", "description", "author"]:
        op.add_column("captures", sa.Column(name, sa.String(), nullable=True))
    op.add_column("captures", sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("jobs", sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("worker_id", sa.String(), nullable=True))
    op.create_table(
        "newsletters",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("introduction", sa.Text(), nullable=True),
        sa.Column("items_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_newsletters_user_id", "newsletters", ["user_id"])
    op.create_table(
        "newsletter_captures",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("newsletter_id", sa.String(), sa.ForeignKey("newsletters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capture_id", sa.String(), sa.ForeignKey("captures.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("capture_id", name="uq_newsletter_capture"),
    )


def downgrade() -> None:
    op.drop_table("newsletter_captures")
    op.drop_index("ix_newsletters_user_id", table_name="newsletters")
    op.drop_table("newsletters")
    for name in ["worker_id", "lease_expires_at", "available_at", "max_attempts", "attempts"]:
        op.drop_column("jobs", name)
    for name in ["captured_at", "author", "description", "domain"]:
        op.drop_column("captures", name)
    op.drop_constraint("fk_sessions_user_id", "sessions", type_="foreignkey")
    op.drop_column("sessions", "csrf_token")
    op.drop_column("sessions", "user_id")
    for table in ["retrieval_events", "agent_steps", "llm_calls", "jobs", "revisit_card_feedback", "resources", "revisit_cards", "clusters", "captures"]:
        op.drop_constraint(f"fk_{table}_user_id", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        op.drop_column(table, "user_id")
    op.drop_table("idempotency_keys")
    op.drop_table("extension_tokens")
    op.drop_table("users")
