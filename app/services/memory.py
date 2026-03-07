"""
Conversation memory service — load and save chat history from Postgres.

Two public functions:
  load_history(tenant_id, chat_id, db)
    → list of {role, content} dicts, ordered oldest-first.
    → Used to build the LLM prompt with full conversation context.

  save_turn(tenant_id, chat_id, user_text, assistant_text, id_message, db)
    → Inserts one user Message + one assistant Message.
    → Called after the graph produces a reply.

Design decisions:
  - We load the last MAX_HISTORY_MESSAGES turns (configurable).
    More than ~20 turns fills the context window and slows the LLM.
  - Messages are ordered by created_at ascending so the LLM sees oldest first.
  - No summarization yet — Phase 5 will add an LLM summarizer that compresses
    old messages into a single "summary" row when history exceeds a token limit.
  - All queries filter by tenant_id first (app-layer multi-tenancy).

Token budget awareness:
  We don't count tokens here — that's Phase 5.
  For now, MAX_HISTORY_MESSAGES = 20 is a safe limit for most models.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message

logger = logging.getLogger(__name__)

# Maximum number of past messages to load into the LLM context.
# Each message pair (user + assistant) = 2 rows.
# 20 messages = 10 conversation turns.
MAX_HISTORY_MESSAGES = 20


async def load_history(
    tenant_id: str,
    chat_id: str,
    db: AsyncSession,
    limit: int = MAX_HISTORY_MESSAGES,
) -> list[dict[str, Any]]:
    """
    Load the recent conversation history for a given chat.

    Returns a list of {role, content} dicts ordered oldest-first,
    ready to be inserted into LLM messages as the conversation history.

    Args:
        tenant_id: UUID string of the tenant.
        chat_id:   WhatsApp chat ID (e.g. "972501234567@c.us").
        db:        Async SQLAlchemy session.
        limit:     Max messages to return (default: MAX_HISTORY_MESSAGES).

    Returns:
        [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
    """
    # Subquery: get the N most recent messages (ordered DESC to get the latest)
    # Then reverse them so the final list is oldest-first (correct for LLM).
    result = await db.execute(
        select(Message)
        .where(
            Message.tenant_id == uuid.UUID(tenant_id),
            Message.chat_id == chat_id,
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = result.scalars().all()

    # Reverse to get chronological order (oldest first)
    messages = list(reversed(messages))

    history = [{"role": msg.role, "content": msg.content} for msg in messages]

    logger.debug(
        "memory:load tenant=%s chat=%s messages=%d",
        tenant_id,
        chat_id,
        len(history),
    )
    return history


async def save_turn(
    tenant_id: str,
    chat_id: str,
    user_text: str,
    assistant_text: str,
    db: AsyncSession,
    id_message: str | None = None,
) -> None:
    """
    Persist one conversation turn (user message + assistant reply).

    Both messages are inserted in a single flush so they share the same
    implicit transaction.

    Args:
        tenant_id:      UUID string of the tenant.
        chat_id:        WhatsApp chat ID.
        user_text:      The user's message.
        assistant_text: The reply the agent sent.
        db:             Async SQLAlchemy session.
        id_message:     Green API idMessage (optional, for cross-reference).
    """
    tid = uuid.UUID(tenant_id)

    user_msg = Message(
        id=uuid.uuid4(),
        tenant_id=tid,
        chat_id=chat_id,
        role="user",
        content=user_text,
        id_message=id_message,
    )
    assistant_msg = Message(
        id=uuid.uuid4(),
        tenant_id=tid,
        chat_id=chat_id,
        role="assistant",
        content=assistant_text,
        id_message=None,  # assistant messages have no Green API id
    )

    db.add(user_msg)
    db.add(assistant_msg)
    await db.flush()  # write to DB within the current transaction

    logger.debug(
        "memory:save tenant=%s chat=%s user_len=%d assistant_len=%d",
        tenant_id,
        chat_id,
        len(user_text),
        len(assistant_text),
    )


async def get_message_count(
    tenant_id: str,
    chat_id: str,
    db: AsyncSession,
) -> int:
    """
    Return the total number of messages stored for a chat.

    Used in tests and for Phase 5 summarization trigger logic.
    """
    from sqlalchemy import func

    result = await db.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == uuid.UUID(tenant_id),
            Message.chat_id == chat_id,
        )
    )
    return result.scalar_one()
