"""
Unit tests for the escalate tool (app/services/tools/escalate.py).

These are pure unit tests — no DB, no LLM, no network.
The escalate tool is simple today (Phase 3 stub) but the tests establish
the contract that future phases must not break:
  - Always returns a handoff_message
  - Message is the canonical Hebrew handoff string
  - Never raises for any valid inputs
"""

import pytest

from app.services.tools.escalate import HANDOFF_MESSAGE, escalate_to_human


class TestEscalateToHuman:
    async def test_returns_handoff_message_key(self):
        result = await escalate_to_human(
            tenant_id="tenant-123",
            phone_number="972501234567",
            reason="user requested human",
        )
        assert "handoff_message" in result

    async def test_handoff_message_is_canonical_string(self):
        """The message must match the constant — clients depend on this exact text."""
        result = await escalate_to_human("t", "p", "r")
        assert result["handoff_message"] == HANDOFF_MESSAGE

    async def test_handoff_message_is_non_empty(self):
        result = await escalate_to_human("t", "p", "r")
        assert len(result["handoff_message"]) > 0

    async def test_works_with_empty_reason(self):
        """Reason is optional context — empty string must not crash."""
        result = await escalate_to_human("t", "p", reason="")
        assert "handoff_message" in result

    async def test_returns_only_handoff_message_key(self):
        result = await escalate_to_human("t", "p", "r")
        assert list(result.keys()) == ["handoff_message"]
