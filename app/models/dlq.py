"""
Dead Letter Queue (DLQ) event model.

When a message fails processing (after all ARQ retries), it's saved here.
The replay worker (`dlq_replay.py`) re-enqueues pending DLQ events.

Why Postgres and not Redis for the DLQ?
  - We need durability: DLQ events must survive restarts.
  - We need queryability: "show me all failed messages for tenant X".
  - Redis TTLs would silently expire unplayed events.

Lifecycle:
  1. Job fails in process_message → DLQ event saved with status="pending"
  2. Admin reviews DLQ events (future: admin CLI / dashboard)
  3. Replay script re-enqueues → status="replayed"
  4. If replay succeeds → status="resolved"
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DLQEvent(Base, TimestampMixin):
    """
    A message that failed processing and needs manual review or replay.
    """

    __tablename__ = "dlq_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Tenant context
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    instance_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(100), nullable=False)
    id_message: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # The full job payload (so we can re-enqueue it exactly as-is)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Failure context
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Lifecycle status
    # pending   → waiting for replay
    # replayed  → re-enqueued (not yet confirmed successful)
    # resolved  → successfully processed after replay
    # abandoned → manually marked as not worth replaying
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)

    def __repr__(self) -> str:
        return (
            f"<DLQEvent tenant={self.tenant_id!s:.8} "
            f"chat={self.chat_id!r} status={self.status!r}>"
        )
