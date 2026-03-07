"""
Unit tests for the qualify_lead tool (app/services/tools/qualify_lead.py).

Strategy: mock litellm.acompletion — no real LLM calls.
We test the JSON parsing logic and the safe defaults on failure.

Key cases:
  1. Qualified lead — correct fields returned
  2. Ready to book — ready_to_book=True
  3. Should escalate — should_escalate=True
  4. Disqualified — status=disqualified
  5. LLM returns invalid JSON — safe defaults returned (no crash)
  6. LLM raises exception — safe defaults returned (no crash)
  7. Missing fields in LLM response — defaults fill the gaps
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tools.qualify_lead import qualify_lead


def _mock_llm_response(payload: dict) -> MagicMock:
    """Build a mock LiteLLM response that returns the given dict as JSON."""
    mock = MagicMock()
    mock.choices[0].message.content = json.dumps(payload)
    return mock


async def _call(text: str = "I'm interested", response: dict | None = None) -> dict:
    """Helper: call qualify_lead with a mocked LLM."""
    resp = _mock_llm_response(
        response
        or {
            "status": "qualified",
            "reason": "interested lead",
            "ready_to_book": False,
            "should_escalate": False,
        }
    )
    with patch("litellm.acompletion", AsyncMock(return_value=resp)):
        return await qualify_lead(
            text=text,
            context=["Hair transplant FAQ"],
            llm_model="anthropic/claude-sonnet-4-6",
            system_prompt="You are a sales agent",
        )


class TestQualifyLeadParsing:
    async def test_qualified_status_is_returned(self):
        result = await _call(response={"status": "qualified", "reason": "ok", "ready_to_book": False, "should_escalate": False})
        assert result["status"] == "qualified"

    async def test_disqualified_status_is_returned(self):
        result = await _call(response={"status": "disqualified", "reason": "not suitable", "ready_to_book": False, "should_escalate": False})
        assert result["status"] == "disqualified"

    async def test_ready_to_book_true(self):
        result = await _call(response={"status": "qualified", "reason": "wants to book", "ready_to_book": True, "should_escalate": False})
        assert result["ready_to_book"] is True

    async def test_ready_to_book_false(self):
        result = await _call(response={"status": "qualified", "reason": "exploring", "ready_to_book": False, "should_escalate": False})
        assert result["ready_to_book"] is False

    async def test_should_escalate_true(self):
        result = await _call(
            text="I want to talk to a human",
            response={"status": "undecided", "reason": "user wants human", "ready_to_book": False, "should_escalate": True},
        )
        assert result["should_escalate"] is True

    async def test_reason_is_returned(self):
        result = await _call(response={"status": "qualified", "reason": "very interested", "ready_to_book": False, "should_escalate": False})
        assert result["reason"] == "very interested"

    async def test_all_fields_present_in_result(self):
        result = await _call()
        assert set(result.keys()) == {"status", "reason", "ready_to_book", "should_escalate"}


class TestQualifyLeadDefaults:
    async def test_missing_fields_get_defaults(self):
        """LLM returns only partial JSON — missing fields get safe defaults."""
        resp = _mock_llm_response({"status": "qualified"})
        with patch("litellm.acompletion", AsyncMock(return_value=resp)):
            result = await qualify_lead("hi", [], "model", "prompt")
        assert result["status"] == "qualified"
        assert result["ready_to_book"] is False
        assert result["should_escalate"] is False
        assert result["reason"] == ""

    async def test_invalid_json_returns_safe_defaults(self):
        """LLM returns garbage — must not crash."""
        mock = MagicMock()
        mock.choices[0].message.content = "not json at all"
        with patch("litellm.acompletion", AsyncMock(return_value=mock)):
            result = await qualify_lead("hi", [], "model", "prompt")
        assert result["status"] == "undecided"
        assert result["ready_to_book"] is False
        assert result["should_escalate"] is False

    async def test_llm_exception_returns_safe_defaults(self):
        """LLM call raises — must not propagate exception."""
        with patch("litellm.acompletion", AsyncMock(side_effect=Exception("LLM unreachable"))):
            result = await qualify_lead("hi", [], "model", "prompt")
        assert result["status"] == "undecided"
        assert result["ready_to_book"] is False
        assert result["should_escalate"] is False

    async def test_empty_content_returns_safe_defaults(self):
        mock = MagicMock()
        mock.choices[0].message.content = None
        with patch("litellm.acompletion", AsyncMock(return_value=mock)):
            result = await qualify_lead("hi", [], "model", "prompt")
        assert result["status"] == "undecided"
