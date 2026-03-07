"""Add messages table for conversation memory.

Revision ID: 002
Revises: 001
Create Date: 2026-03-07

Why a separate migration?
  The messages table is Phase 4 functionality added after the initial schema.
  Keeping migrations separate means we can roll back just this table without
  touching the tenant schema.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), nullable=False),
        # tenant_id comes from TenantMixin — all queries filter by this
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # chat_id is the WhatsApp chat identifier (e.g. "972501234567@c.us")
        sa.Column("chat_id", sa.String(length=100), nullable=False),
        # role: "user" or "assistant"
        sa.Column("role", sa.String(length=20), nullable=False),
        # The message text
        sa.Column("content", sa.Text(), nullable=False),
        # Green API idMessage — for cross-referencing with dedup Redis key
        sa.Column("id_message", sa.String(length=100), nullable=True),
        # Timestamps — created_at is the ordering key
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Index for the primary query: all messages for a tenant+chat, ordered by time
    op.create_index(
        "ix_messages_tenant_chat",
        "messages",
        ["tenant_id", "chat_id", "created_at"],
    )

    # Index for tenant_id alone (used by TenantMixin-style queries)
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"])
    op.create_index("ix_messages_chat_id", "messages", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_chat_id", table_name="messages")
    op.drop_index("ix_messages_tenant_id", table_name="messages")
    op.drop_index("ix_messages_tenant_chat", table_name="messages")
    op.drop_table("messages")
