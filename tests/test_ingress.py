"""
Unit tests for the ingress pipeline (app/services/ingress.py).

Strategy: mock the DB session, Redis, and ARQ.
We test the pipeline logic in isolation — not the DB or Redis internals.

Why mock and not use real DB/Redis here?
  - These are UNIT tests — they test the ingress logic, not the DB queries.
  - Integration tests (test_tenant_router.py) cover the real DB path.
  - With mocks, tests run in milliseconds with no Docker required.

Key test cases:
  1. Happy path: valid incoming text → dispatched to ARQ
  2. Outgoing message → filtered
  3. Group message → filtered
  4. Empty text (image with no caption) → filtered
  5. Duplicate message (same idMessage) → filtered by dedup
  6. Unknown instance_id (tenant not found) → rejected
  7. Malformed JSON body → rejected
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.ingress import IngressResult, handle_webhook
from tests.fixtures.greenapi_payloads import (
    group_message,
    image_message_no_caption,
    image_message_with_caption,
    incoming_text,
    outgoing_message,
    state_change,
)

INSTANCE_ID = "1234567"


def make_mock_db():
    """Returns a mock AsyncSession that routes tenant_router to raise TenantNotFoundError."""
    return AsyncMock()


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def run_ingress(
    payload: dict,
    *,
    instance_id: str = INSTANCE_ID,
    fake_redis=None,
    mock_arq=None,
    tenant_found: bool = True,
) -> IngressResult:
    """
    Helper that patches get_redis() and get_tenant_by_instance_id(),
    then runs handle_webhook().
    """
    import uuid
    from unittest.mock import MagicMock

    db = make_mock_db()
    arq = mock_arq or AsyncMock()

    # Build fake Tenant + TenantChannel objects
    if tenant_found:
        fake_tenant = MagicMock()
        fake_tenant.id = uuid.uuid4()
        fake_tenant.slug = "test-tenant"
        fake_tenant.graph_type = "iroko"

        fake_channel = MagicMock()
        fake_channel.tenant_id = fake_tenant.id

        tenant_patch = AsyncMock(return_value=(fake_tenant, fake_channel))
    else:
        from app.services.tenant_router import TenantNotFoundError
        tenant_patch = AsyncMock(side_effect=TenantNotFoundError("not found"))

    with (
        patch("app.services.ingress.get_tenant_by_instance_id", tenant_patch),
        patch("app.services.ingress.get_redis", return_value=fake_redis),
    ):
        return await handle_webhook(instance_id, payload, db, arq)


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestHappyPath:
    async def test_valid_incoming_text_is_accepted(self, fake_redis, mock_arq):
        result = await run_ingress(
            incoming_text(text="שלום", id_message="msg-001"),
            fake_redis=fake_redis,
            mock_arq=mock_arq,
        )
        assert result.accepted is True
        assert result.reason == "dispatched"

    async def test_dispatches_job_to_arq(self, fake_redis, mock_arq):
        await run_ingress(
            incoming_text(text="שלום", id_message="msg-002"),
            fake_redis=fake_redis,
            mock_arq=mock_arq,
        )
        mock_arq.enqueue_job.assert_called_once()
        call_args = mock_arq.enqueue_job.call_args
        assert call_args[0][0] == "process_message"
        job_payload = call_args[0][1]
        assert job_payload["text"] == "שלום"
        assert job_payload["instance_id"] == INSTANCE_ID

    async def test_image_with_caption_is_accepted(self, fake_redis, mock_arq):
        result = await run_ingress(
            image_message_with_caption(caption="הנה התמונה שלי", id_message="msg-img-001"),
            fake_redis=fake_redis,
            mock_arq=mock_arq,
        )
        assert result.accepted is True


class TestFiltering:
    async def test_outgoing_message_is_filtered(self, fake_redis, mock_arq):
        result = await run_ingress(outgoing_message(), fake_redis=fake_redis, mock_arq=mock_arq)
        assert result.accepted is False
        assert "outgoingMessageReceived" in result.reason

    async def test_group_message_is_filtered(self, fake_redis, mock_arq):
        result = await run_ingress(group_message(), fake_redis=fake_redis, mock_arq=mock_arq)
        assert result.accepted is False
        assert result.reason == "group_message"

    async def test_state_change_is_filtered(self, fake_redis, mock_arq):
        result = await run_ingress(state_change(), fake_redis=fake_redis, mock_arq=mock_arq)
        assert result.accepted is False

    async def test_image_without_caption_is_filtered(self, fake_redis, mock_arq):
        result = await run_ingress(
            image_message_no_caption(), fake_redis=fake_redis, mock_arq=mock_arq
        )
        assert result.accepted is False
        assert result.reason == "empty_text"

    async def test_filtered_messages_do_not_enqueue(self, fake_redis, mock_arq):
        await run_ingress(outgoing_message(), fake_redis=fake_redis, mock_arq=mock_arq)
        mock_arq.enqueue_job.assert_not_called()


class TestDedup:
    async def test_first_message_is_accepted(self, fake_redis, mock_arq):
        result = await run_ingress(
            incoming_text(id_message="unique-msg-001"),
            fake_redis=fake_redis,
            mock_arq=mock_arq,
        )
        assert result.accepted is True

    async def test_duplicate_message_is_rejected(self, fake_redis, mock_arq):
        payload = incoming_text(id_message="dup-msg-001")

        # First delivery
        first = await run_ingress(payload, fake_redis=fake_redis, mock_arq=mock_arq)
        assert first.accepted is True

        # Second delivery (same idMessage) — simulates Green API retry
        second = await run_ingress(payload, fake_redis=fake_redis, mock_arq=mock_arq)
        assert second.accepted is False
        assert second.reason == "duplicate"

    async def test_duplicate_does_not_enqueue_twice(self, fake_redis, mock_arq):
        payload = incoming_text(id_message="dup-msg-002")
        await run_ingress(payload, fake_redis=fake_redis, mock_arq=mock_arq)
        await run_ingress(payload, fake_redis=fake_redis, mock_arq=mock_arq)

        # enqueue_job should have been called exactly once
        assert mock_arq.enqueue_job.call_count == 1

    async def test_different_messages_are_both_accepted(self, fake_redis, mock_arq):
        result1 = await run_ingress(
            incoming_text(id_message="msg-A"), fake_redis=fake_redis, mock_arq=mock_arq
        )
        result2 = await run_ingress(
            incoming_text(id_message="msg-B"), fake_redis=fake_redis, mock_arq=mock_arq
        )
        assert result1.accepted is True
        assert result2.accepted is True


class TestTenantRouting:
    async def test_unknown_instance_is_rejected(self, fake_redis, mock_arq):
        result = await run_ingress(
            incoming_text(),
            fake_redis=fake_redis,
            mock_arq=mock_arq,
            tenant_found=False,
        )
        assert result.accepted is False
        assert result.reason == "tenant_not_found"

    async def test_unknown_instance_does_not_enqueue(self, fake_redis, mock_arq):
        await run_ingress(
            incoming_text(),
            fake_redis=fake_redis,
            mock_arq=mock_arq,
            tenant_found=False,
        )
        mock_arq.enqueue_job.assert_not_called()


class TestParseError:
    async def test_invalid_payload_is_rejected(self, fake_redis, mock_arq):
        """If Green API sends something unexpected, we must not crash."""
        result = await run_ingress(
            {"completely": "wrong", "payload": True},
            fake_redis=fake_redis,
            mock_arq=mock_arq,
        )
        assert result.accepted is False
        assert result.reason == "parse_error"
