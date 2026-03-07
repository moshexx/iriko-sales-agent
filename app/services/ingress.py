"""
Ingress pipeline — the first thing that runs when a webhook arrives.

Steps:
1. Parse the raw JSON into a typed GreenAPIWebhook
2. Filter — drop events we don't process (outgoing, groups, calls, status changes)
3. Dedup — if we've already processed this idMessage, drop it silently
4. Dispatch — push a job to the ARQ queue for async processing

Why async dispatch?
  The webhook endpoint must return 200 to Green API within ~5 seconds or it will
  retry. LLM calls can take 5–30 seconds. So we accept the message immediately
  and process it in the background worker.

Why dedup?
  Green API (and any webhook provider) may deliver the same message more than once
  (network retries, restarts). Idempotency key = idMessage.
"""

import json
import logging
from dataclasses import dataclass

from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant, TenantChannel
from app.redis_client import get_redis
from app.schemas.greenapi import GreenAPIWebhook
from app.services.tenant_router import TenantNotFoundError, get_tenant_by_instance_id

logger = logging.getLogger(__name__)

# How long to remember a processed idMessage (24 hours)
DEDUP_TTL_SECONDS = 86400


@dataclass
class IngressResult:
    accepted: bool
    reason: str  # for logging/debugging


async def handle_webhook(
    instance_id: str,
    raw_payload: dict,
    db: AsyncSession,
    arq: ArqRedis,
) -> IngressResult:
    """
    Full ingress pipeline. Returns IngressResult indicating if the message was accepted.
    """

    # ── Step 1: Parse ──────────────────────────────────────────────────────────
    try:
        event = GreenAPIWebhook.model_validate(raw_payload)
    except Exception as exc:
        logger.warning("Failed to parse Green API payload: %s | payload=%s", exc, raw_payload)
        return IngressResult(accepted=False, reason="parse_error")

    # ── Step 2: Filter ─────────────────────────────────────────────────────────
    if not event.is_incoming:
        # outgoingMessageReceived, stateInstanceChanged, incomingCall, etc.
        return IngressResult(accepted=False, reason=f"ignored_type:{event.type_webhook}")

    if event.is_group_message:
        # Group messages not supported in MVP
        logger.debug("Dropping group message chat_id=%s", event.chat_id)
        return IngressResult(accepted=False, reason="group_message")

    if not event.message_data:
        return IngressResult(accepted=False, reason="no_message_data")

    text = event.message_data.extract_text().strip()
    if not text:
        # Image/file with no caption — log and drop (handled via human handoff in agent)
        logger.debug("Dropping empty-text message id=%s type=%s", event.id_message, event.message_data.type_message)
        return IngressResult(accepted=False, reason="empty_text")

    # ── Step 3: Tenant lookup ──────────────────────────────────────────────────
    try:
        tenant, channel = await get_tenant_by_instance_id(instance_id, db)
    except TenantNotFoundError as exc:
        logger.warning("Unknown instance_id=%s: %s", instance_id, exc)
        return IngressResult(accepted=False, reason="tenant_not_found")

    # ── Step 4: Dedup ──────────────────────────────────────────────────────────
    redis = get_redis()
    dedup_key = f"dedup:{instance_id}:{event.id_message}"

    already_seen = await redis.set(dedup_key, "1", ex=DEDUP_TTL_SECONDS, nx=True)
    if not already_seen:
        logger.info("Duplicate message id=%s — skipping", event.id_message)
        return IngressResult(accepted=False, reason="duplicate")

    # ── Step 5: Dispatch to ARQ queue ─────────────────────────────────────────
    job_payload = {
        "instance_id": instance_id,
        "tenant_id": str(tenant.id),
        "graph_type": tenant.graph_type,
        "chat_id": event.chat_id,
        "phone_number": event.phone_number,
        "sender_name": event.sender_data.sender_name if event.sender_data else "",
        "id_message": event.id_message,
        "text": text,
        "type_message": event.message_data.type_message,
        "timestamp": event.timestamp,
    }

    await arq.enqueue_job("process_message", job_payload)

    logger.info(
        "Accepted message tenant=%s chat=%s id=%s len=%d",
        tenant.slug,
        event.chat_id,
        event.id_message,
        len(text),
    )

    return IngressResult(accepted=True, reason="dispatched")
