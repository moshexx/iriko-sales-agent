"""Add missing fallback_token_ref column to tenant_channels.

Revision ID: 004
Revises: 003
Create Date: 2026-03-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_channels",
        sa.Column("fallback_token_ref", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_channels", "fallback_token_ref")
