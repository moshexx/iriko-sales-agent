"""
Unit tests for the book_meeting tool (app/services/tools/book_meeting.py).

Phase 3 is a stub (no real calendar). These tests verify the contract:
  - Always returns a confirmation_message
  - Message includes a booking link (http/https)
  - Message includes the sender's name when provided
  - Works when name is empty (anonymous lead)
"""

import pytest

from app.services.tools.book_meeting import book_meeting


class TestBookMeeting:
    async def test_returns_confirmation_message_key(self):
        result = await book_meeting(
            tenant_id="tenant-123",
            phone_number="972501234567",
            sender_name="יוסי",
        )
        assert "confirmation_message" in result

    async def test_confirmation_message_is_non_empty(self):
        result = await book_meeting("t", "p", "David")
        assert len(result["confirmation_message"]) > 0

    async def test_includes_booking_link(self):
        """The message must contain a clickable link for the user."""
        result = await book_meeting("t", "p", "David")
        assert "http" in result["confirmation_message"]

    async def test_includes_sender_name_when_provided(self):
        result = await book_meeting("t", "p", "David")
        assert "David" in result["confirmation_message"]

    async def test_works_without_sender_name(self):
        """Anonymous lead — no name in message, but must not crash."""
        result = await book_meeting("t", "p", "")
        assert "confirmation_message" in result
        assert len(result["confirmation_message"]) > 0

    async def test_returns_only_confirmation_message_key(self):
        result = await book_meeting("t", "p", "r")
        assert list(result.keys()) == ["confirmation_message"]
