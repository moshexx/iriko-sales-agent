"""
ARQ background worker — processes a single inbound WhatsApp message end-to-end.

How ARQ works:
  ARQ is a Redis-backed job queue for Python async.
  The webhook handler enqueues a job: await arq.enqueue_job("process_message", payload)
  This worker picks it up and runs it asynchronously — completely separate from the HTTP request.

Why this matters:
  LLM calls take 5–30 seconds. We can't block the webhook response that long.
  The worker has as much time as it needs.

WorkerSettings tells ARQ which functions are jobs and how to connect to Redis.
"""

import logging
from typing import Any

from arq import ArqRedis
from arq.connections import RedisSettings

from app.config import settings

logger = logging.getLogger(__name__)


async def process_message(ctx: dict, payload: dict[str, Any]) -> None:
    """
    Main job: process one inbound WhatsApp message end-to-end.

    payload keys:
      instance_id, tenant_id, graph_type, chat_id, phone_number,
      sender_name, id_message, text, type_message, timestamp

    Delegates to agent_orchestrator which:
      1. Loads tenant config from DB
      2. Runs the correct LangGraph graph
      3. Sends the reply via Green API
    """
    from app.services.agent_orchestrator import run_agent

    logger.info(
        "worker:process_message tenant=%s chat=%s graph=%s text_len=%d",
        payload.get("tenant_id"),
        payload.get("chat_id"),
        payload.get("graph_type"),
        len(payload.get("text") or ""),
    )

    attempt = ctx.get("job_try", 1)

    async with ctx["db_factory"]() as db:
        try:
            await run_agent(payload, db)
            await db.commit()
        except Exception as exc:
            logger.exception(
                "worker:process_message FAILED tenant=%s chat=%s attempt=%d error=%s",
                payload.get("tenant_id"),
                payload.get("chat_id"),
                attempt,
                exc,
            )
            from app.workers.dlq_replay import save_to_dlq

            async with ctx["db_factory"]() as dlq_db:
                await save_to_dlq(payload, exc, attempt, dlq_db)
            raise  # re-raise so ARQ can retry (up to max_tries)


async def startup(ctx: dict) -> None:
    """Called once when the worker starts."""
    from app.db import AsyncSessionLocal
    from app.redis_client import get_redis

    ctx["db_factory"] = AsyncSessionLocal
    ctx["redis"] = get_redis()
    logger.info("Worker started")


async def shutdown(ctx: dict) -> None:
    """Called once when the worker shuts down."""
    from app.redis_client import close_redis

    await close_redis()
    logger.info("Worker stopped")


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [process_message]
    on_startup = startup
    on_shutdown = shutdown

    redis_settings = RedisSettings.from_dsn(settings.redis_url)

    # Retry failed jobs up to 3 times with exponential backoff
    max_tries = 3

    # Job timeout: 120 seconds (plenty for LLM + tool calls)
    job_timeout = 120

    # How many jobs to run concurrently per worker process
    # Keep low to avoid hammering external APIs per tenant
    max_jobs = 10
