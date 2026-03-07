"""
Tenant model — the core of multi-tenancy.

Every business that uses LeadWise is a "tenant". They have their own:
- Green API instance(s) (phone numbers)
- LLM config
- CRM integration
- Conversation graph type (iroko, dng, ...)
- System prompt / persona
"""

import uuid
from enum import StrEnum

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class GraphType(StrEnum):
    IROKO = "iroko"
    DNG = "dng"


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Conversation graph to use for this tenant
    graph_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # System prompt / bot persona
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LLM config (overrides platform default)
    llm_model: Mapped[str] = mapped_column(String(128), default="anthropic/claude-sonnet-4-6")
    llm_api_key_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)  # secret ref

    # Qdrant collection name for this tenant's knowledge base
    qdrant_collection: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Rate limiting
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, default=60)

    # Monthly LLM token cap (0 = unlimited)
    llm_monthly_token_cap: Mapped[int] = mapped_column(Integer, default=0)

    # Extra per-tenant config (flexible JSON for future use)
    extra_config: Mapped[dict] = mapped_column(JSON, default=dict)


class TenantChannel(Base, TimestampMixin):
    """
    A phone number / Green API instance belonging to a tenant.
    One tenant can have multiple channels (e.g. sales + support).
    """

    __tablename__ = "tenant_channels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # Green API credentials for this channel
    instance_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    token_ref: Mapped[str] = mapped_column(String(255), nullable=False)  # secret ref

    # Optional fallback instance if primary is blocked/disconnected
    fallback_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fallback_token_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    label: Mapped[str] = mapped_column(String(64), default="default")  # e.g. "sales", "support"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class TenantIntegration(Base, TimestampMixin):
    """
    External CRM / payment / calendar integrations per tenant.
    Each integration stores its type and credentials reference.
    """

    __tablename__ = "tenant_integrations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    integration_type: Mapped[str] = mapped_column(String(64), nullable=False)  # crm, payment, calendar
    provider: Mapped[str] = mapped_column(String(64), nullable=False)  # biznness, hype, calendly
    credentials_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)  # secret ref
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
