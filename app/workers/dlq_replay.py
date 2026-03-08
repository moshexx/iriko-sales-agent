"""
DLQ replay worker — re-enqueues failed messages from the dead letter queue.

How to run:
    arq app.workers.dlq_replay.ReplayWorkerSettings

Or as a one-shot script:
    python -m app.workers.dlq_replay

What it does:
  1. Query dlq_events WHERE status='pending' ORDER BY created_at ASC LIMIT batch_size
  2. For each event: re-enqueue the original payload via ARQ
  3. Mark the event status='replayed'

Retry semantics:
  The re-enqueued job is subject to the normal WorkerSettings.max_tries.
  If it succeeds → the admin should manually mark it 'resolved' (future: auto-update).
  If it fails again → a NEW DLQ event will be created (attempt incremented).

Safety:
  We process in small batches (BATCH_SIZE=50) to avoid overwhelming the queue.
  A failed replay is logged but doesn't crash the replay job.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


async def replay_dlq(ctx: dict) -> dict[str, Any]:
    """
    ARQ job: replay one batch of pending DLQ events.

    Returns a summary dict with counts.
    """
    from sqlalchemy import select, update

    from app.db import AsyncSessionLocal
    from app.models.dlq import DLQEvent

    replayed = 0
    failed = 0

    async with AsyncSessionLocal() as db:
        # Load the oldest pending events
        result = await db.execute(
            select(DLQEvent)
            .where(DLQEvent.status == "pending")
            .order_by(DLQEvent.created_at.asc())
            .limit(BATCH_SIZE)
        )
        events = result.scalars().all()

        if not events:
            logger.info("dlq_replay:empty — no pending events")
            return {"replayed": 0, "failed": 0, "total": 0}

        logger.info("dlq_replay:start batch=%d", len(events))

        arq = ctx.get("arq")
        if arq is None:
            logger.error("dlq_replay:no_arq — ctx missing arq pool")
            return {"replayed": 0, "failed": 0, "total": len(events)}

        for event in events:
            try:
                await arq.enqueue_job(
                    "process_message",
                    event.payload,
                    _job_id=f"dlq-replay-{event.id}",  # deterministic job ID to avoid duplicates
                )

                # Mark as replayed
                await db.execute(
                    update(DLQEvent)
                    .where(DLQEvent.id == event.id)
                    .values(status="replayed")
                )
                replayed += 1
                logger.info(
                    "dlq_replay:enqueued event=%s tenant=%s chat=%s",
                    event.id,
                    event.tenant_id,
                    event.chat_id,
                )

            except Exception as exc:
                failed += 1
                logger.exception(
                    "dlq_replay:failed event=%s error=%s",
                    event.id,
                    exc,
                )

        await db.commit()

    logger.info("dlq_replay:done replayed=%d failed=%d", replayed, failed)
    return {"replayed": replayed, "failed": failed, "total": len(events)}


async def save_to_dlq(
    payload: dict[str, Any],
    error: Exception,
    attempt: int,
    db,
) -> None:
    """
    Save a failed job to the DLQ.

    Called from process_message when the job fails.
    Uses db.flush() so the caller controls the commit.

    Args:
        payload: the full ARQ job payload
        error:   the exception that caused the failure
        attempt: which retry this was (from ctx["job_try"])
        db:      AsyncSession
    """
    import uuid

    from app.models.dlq import DLQEvent

    event = DLQEvent(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(payload.get("tenant_id", str(uuid.uuid4()))),
        instance_id=payload.get("instance_id", ""),
        chat_id=payload.get("chat_id", ""),
        id_message=payload.get("id_message"),
        payload=payload,
        error_message=f"{type(error).__name__}: {error}"[:1000],
        attempt=attempt,
        status="pending",
    )
    db.add(event)
    await db.flush()

    logger.warning(
        "dlq:saved tenant=%s chat=%s attempt=%d error=%s",
        payload.get("tenant_id"),
        payload.get("chat_id"),
        attempt,
        type(error).__name__,
    )


class ReplayWorkerSettings:
    """ARQ worker settings for the DLQ replay worker."""

    import os

    from arq.connections import RedisSettings

    functions = [replay_dlq]
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:6379")
    )

    # Replay runs on a schedule — every 5 minutes
    cron_jobs = []  # TODO: add cron_job(replay_dlq, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55})
