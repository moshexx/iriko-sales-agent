"""
Agent orchestrator — runs the LangGraph agent for one inbound message.

This is the bridge between the ARQ worker and the LangGraph graph.

Responsibilities:
  1. Load tenant config from DB (system_prompt, llm_model, qdrant_collection, etc.)
  2. Build the initial AgentState from the job payload + tenant config.
  3. Run the graph (ainvoke).
  4. Send the reply text back to the user via Green API.
  5. Handle errors gracefully — log and fail the job so ARQ can retry.

Why is sending the reply HERE and not inside the graph?
  The graph produces reply_text. Sending is a side effect with external I/O.
  Keeping I/O at the orchestrator boundary makes the graph testable in isolation.

Phase 4 will add:
  - Load + store chat history (Postgres) before/after the graph
  - Token usage tracking for cost control (llm_monthly_token_cap)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.graphs.factory import get_graph

logger = logging.getLogger(__name__)

# Default fallbacks — used when tenant config fields are not set
DEFAULT_LLM_MODEL = "anthropic/claude-sonnet-4-6"
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful sales assistant for a hair clinic. "
    "Be friendly, professional, and concise. Respond in the same language as the user."
)


async def run_agent(payload: dict[str, Any], db: AsyncSession) -> None:
    """
    Run the LangGraph agent for one inbound WhatsApp message.

    Args:
        payload:  The ARQ job payload from ingress.py (see ingress for full schema).
        db:       An async SQLAlchemy session for DB lookups.

    Raises:
        Any unhandled exception — ARQ will catch it and retry per WorkerSettings.
    """
    tenant_id = payload["tenant_id"]
    graph_type = payload["graph_type"]
    instance_id = payload["instance_id"]
    chat_id = payload["chat_id"]

    logger.info(
        "orchestrator:start tenant=%s chat=%s graph=%s",
        tenant_id,
        chat_id,
        graph_type,
    )

    # ── 1. Load tenant config ─────────────────────────────────────────────────
    tenant_config = await _load_tenant_config(tenant_id, db)

    # ── 2. Build initial state ────────────────────────────────────────────────
    initial_state = {
        # From the job payload
        "tenant_id": tenant_id,
        "instance_id": instance_id,
        "chat_id": chat_id,
        "phone_number": payload.get("phone_number", ""),
        "sender_name": payload.get("sender_name", ""),
        "text": payload.get("text", ""),
        "id_message": payload.get("id_message", ""),
        "graph_type": graph_type,

        # From tenant config
        "system_prompt": tenant_config["system_prompt"],
        "llm_model": tenant_config["llm_model"],
        "qdrant_collection": tenant_config["qdrant_collection"],

        # Initialized empty — nodes will fill these in
        "retrieved_context": [],
        "qualification": "undecided",
        "qualification_reason": "",
        "reply_text": "",
        "should_book": False,
        "should_escalate": False,
    }

    # ── 3. Get the correct graph and run it ───────────────────────────────────
    graph = get_graph(graph_type)
    final_state = await graph.ainvoke(initial_state)

    # ── 4. Send the reply via Green API ───────────────────────────────────────
    reply_text = final_state.get("reply_text", "")
    if reply_text:
        await _send_reply(
            instance_id=instance_id,
            chat_id=chat_id,
            text=reply_text,
            tenant_config=tenant_config,
        )
    else:
        logger.warning(
            "orchestrator:no_reply tenant=%s chat=%s — graph produced no reply_text",
            tenant_id,
            chat_id,
        )

    logger.info(
        "orchestrator:done tenant=%s chat=%s qualification=%s",
        tenant_id,
        chat_id,
        final_state.get("qualification", "unknown"),
    )


async def _load_tenant_config(tenant_id: str, db: AsyncSession) -> dict[str, Any]:
    """
    Load the tenant's runtime config from the DB.

    Returns a dict with all fields needed to run the agent.
    Falls back to defaults if fields are not set.
    """
    from sqlalchemy import select

    from app.models.tenant import Tenant, TenantChannel

    result = await db.execute(
        select(Tenant).where(Tenant.id == uuid.UUID(tenant_id))
    )
    tenant = result.scalar_one_or_none()

    if tenant is None:
        # Should not happen — ingress already verified the tenant exists.
        # But if the tenant was deleted between ingress and worker execution, fail loudly.
        raise ValueError(f"Tenant {tenant_id} not found — was it deleted?")

    return {
        "system_prompt": tenant.system_prompt or DEFAULT_SYSTEM_PROMPT,
        "llm_model": tenant.llm_model or DEFAULT_LLM_MODEL,
        "qdrant_collection": tenant.qdrant_collection or f"{tenant.slug}_knowledge",
        "green_api_token_ref": None,  # Phase 4: load from secrets store
    }


async def _send_reply(
    instance_id: str,
    chat_id: str,
    text: str,
    tenant_config: dict[str, Any],
) -> None:
    """
    Send a text message to the user via the Green API.

    Phase 3 stub: logs the reply instead of sending.
    Phase 4 will add:
      - Real Green API client (httpx)
      - Typing indicator simulation (sendTyping before the reply)
      - Markdown → WhatsApp plain text conversion
      - Retry on Green API errors
    """
    # TODO Phase 4: real Green API client
    # from app.services.greenapi_client import GreenAPIClient
    # async with GreenAPIClient(instance_id, token) as client:
    #     await client.send_typing(chat_id)
    #     await asyncio.sleep(min(len(text) / 50, 3))   # simulate typing
    #     await client.send_message(chat_id, text)

    logger.info(
        "orchestrator:reply_stub instance=%s chat=%s text_len=%d",
        instance_id,
        chat_id,
        len(text),
    )
    logger.debug("orchestrator:reply_text %r", text[:200])
