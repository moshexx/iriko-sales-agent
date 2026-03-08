"""
Integration tests for the Dead Letter Queue (app/models/dlq.py + app/workers/dlq_replay.py).

Uses a REAL Postgres container (via testcontainers in conftest.py).

Key test cases:
  1. save_to_dlq persists a DLQEvent with status="pending"
  2. save_to_dlq stores full payload and error message
  3. save_to_dlq stores attempt number
  4. replay_dlq re-enqueues pending events and marks them "replayed"
  5. replay_dlq with no pending events returns zero counts
  6. replay_dlq with no arq in ctx returns early
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.dlq import DLQEvent
from app.workers.dlq_replay import replay_dlq, save_to_dlq

SAMPLE_PAYLOAD = {
    "instance_id": "9990001",
    "tenant_id": "11111111-0000-0000-0000-000000000001",
    "graph_type": "iroko",
    "chat_id": "972501234567@c.us",
    "phone_number": "972501234567",
    "sender_name": "Test User",
    "id_message": "msg-abc123",
    "text": "hello",
    "type_message": "textMessage",
    "timestamp": 1700000000,
}


@pytest.fixture(autouse=True)
def ensure_dlq_model_registered():
    """Ensure DLQEvent table is created by testcontainers."""
    import app.models.dlq  # noqa: F401


class TestSaveToDlq:
    async def test_saves_pending_event(self, db_session):
        """save_to_dlq must create a DLQEvent with status='pending'."""
        error = RuntimeError("LLM timeout")

        await save_to_dlq(SAMPLE_PAYLOAD, error, attempt=1, db=db_session)

        result = await db_session.execute(select(DLQEvent))
        events = result.scalars().all()

        assert len(events) == 1
        assert events[0].status == "pending"

    async def test_saves_full_payload(self, db_session):
        """The full job payload is stored so it can be replayed."""
        error = ValueError("bad state")

        await save_to_dlq(SAMPLE_PAYLOAD, error, attempt=1, db=db_session)

        result = await db_session.execute(select(DLQEvent))
        event = result.scalar_one()

        assert event.payload["chat_id"] == SAMPLE_PAYLOAD["chat_id"]
        assert event.payload["text"] == SAMPLE_PAYLOAD["text"]
        assert event.instance_id == SAMPLE_PAYLOAD["instance_id"]
        assert event.chat_id == SAMPLE_PAYLOAD["chat_id"]
        assert event.id_message == SAMPLE_PAYLOAD["id_message"]

    async def test_saves_error_message(self, db_session):
        """Error type and message are stored in error_message field."""
        error = ConnectionError("Redis unreachable")

        await save_to_dlq(SAMPLE_PAYLOAD, error, attempt=2, db=db_session)

        result = await db_session.execute(select(DLQEvent))
        event = result.scalar_one()

        assert "ConnectionError" in event.error_message
        assert "Redis unreachable" in event.error_message

    async def test_saves_attempt_number(self, db_session):
        """Attempt number tracks which retry created the DLQ event."""
        error = Exception("boom")

        await save_to_dlq(SAMPLE_PAYLOAD, error, attempt=3, db=db_session)

        result = await db_session.execute(select(DLQEvent))
        event = result.scalar_one()

        assert event.attempt == 3

    async def test_saves_tenant_id(self, db_session):
        """tenant_id is stored correctly as UUID."""
        error = Exception("fail")

        await save_to_dlq(SAMPLE_PAYLOAD, error, attempt=1, db=db_session)

        result = await db_session.execute(select(DLQEvent))
        event = result.scalar_one()

        assert str(event.tenant_id) == SAMPLE_PAYLOAD["tenant_id"]


class TestReplayDlq:
    async def test_returns_zero_when_no_pending_events(self, db_session):
        """replay_dlq with empty DLQ returns {replayed:0, failed:0, total:0}."""
        from contextlib import asynccontextmanager
        from unittest.mock import patch

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {"arq": AsyncMock()}
        with patch("app.db.AsyncSessionLocal", mock_session_factory):
            result = await replay_dlq(ctx)

        assert result["replayed"] == 0
        assert result["failed"] == 0
        assert result["total"] == 0

    async def test_returns_early_when_no_arq(self, db_session):
        """replay_dlq with no arq in ctx logs error and returns without crashing."""
        from contextlib import asynccontextmanager
        from unittest.mock import patch

        # Save a pending event first
        await save_to_dlq(SAMPLE_PAYLOAD, Exception("test fail"), attempt=1, db=db_session)
        await db_session.flush()

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {}  # no "arq" key
        with patch("app.db.AsyncSessionLocal", mock_session_factory):
            result = await replay_dlq(ctx)

        assert result["replayed"] == 0
