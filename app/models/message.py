"""
Message model — stores the conversation history per tenant + chat.

Why Postgres and not Redis for history?
  - Redis is ephemeral (TTL-based). Chat history needs to survive restarts.
  - Postgres gives us queryable, persistent, tenant-isolated history.
  - We already have Postgres — no new dependency.

Schema design:
  One row per message turn (user or assistant).
  Ordered by created_at to reconstruct the conversation chronologically.

Multi-tenancy:
  TenantMixin adds tenant_id (UUID, indexed).
  All queries must filter by tenant_id to prevent cross-tenant leakage.

Future phases:
  - Phase 5: Add a summarizer that compresses old messages into a single
    "summary" row when the conversation exceeds MAX_TOKENS.
  - Phase 8: Postgres RLS will enforce tenant_id at the DB engine level.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin


class Message(Base, TenantMixin, TimestampMixin):
    """
    One turn of a conversation — either a user message or an assistant reply.

    A full conversation is reconstructed by querying all Messages for a
    given (tenant_id, chat_id), ordered by created_at.
    """

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    chat_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="WhatsApp chat ID (e.g. '972501234567@c.us')",
    )

    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="'user' or 'assistant'",
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The message text",
    )

    id_message: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Green API idMessage — for cross-referencing with dedup",
    )

    def __repr__(self) -> str:
        return f"<Message role={self.role!r} chat={self.chat_id!r} len={len(self.content)}>"
