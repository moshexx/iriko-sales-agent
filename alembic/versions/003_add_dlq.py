"""Add dlq_events table for dead letter queue.

Revision ID: 003
Revises: 002
Create Date: 2026-03-07

Failed messages are stored here after exhausting ARQ retries.
The replay worker re-enqueues pending events.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dlq_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("instance_id", sa.String(length=64), nullable=False),
        sa.Column("chat_id", sa.String(length=100), nullable=False),
        sa.Column("id_message", sa.String(length=100), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dlq_events_tenant_id", "dlq_events", ["tenant_id"])
    op.create_index("ix_dlq_events_status", "dlq_events", ["status"])
    # Composite index for the replay query: pending events per tenant, oldest first
    op.create_index(
        "ix_dlq_events_status_created",
        "dlq_events",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_dlq_events_status_created", table_name="dlq_events")
    op.drop_index("ix_dlq_events_status", table_name="dlq_events")
    op.drop_index("ix_dlq_events_tenant_id", table_name="dlq_events")
    op.drop_table("dlq_events")
