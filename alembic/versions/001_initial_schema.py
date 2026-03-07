"""Initial schema — tenants, tenant_channels, tenant_integrations.

Revision ID: 001
Revises: (base)
Create Date: 2026-03-07
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("graph_type", sa.String(length=50), nullable=False, server_default="iroko"),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("llm_api_key_ref", sa.String(length=255), nullable=True),
        sa.Column("qdrant_collection", sa.String(length=100), nullable=True),
        sa.Column("rate_limit_rpm", sa.Integer(), nullable=True),
        sa.Column("llm_monthly_token_cap", sa.Integer(), nullable=True),
        sa.Column("extra_config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "tenant_channels",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("instance_id", sa.String(length=50), nullable=False),
        sa.Column("token_ref", sa.String(length=255), nullable=False),
        sa.Column("fallback_instance_id", sa.String(length=50), nullable=True),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instance_id"),
    )
    op.create_index("ix_tenant_channels_instance_id", "tenant_channels", ["instance_id"])

    op.create_table(
        "tenant_integrations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("integration_type", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("credentials_ref", sa.String(length=255), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenant_integrations_tenant_id", "tenant_integrations", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("tenant_integrations")
    op.drop_table("tenant_channels")
    op.drop_table("tenants")
