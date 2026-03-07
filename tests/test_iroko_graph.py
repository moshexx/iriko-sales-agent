"""
Tests for the Iroko LangGraph agent (app/services/graphs/iroko_graph.py).

Two test classes:

TestRouteAfterQualify
  Pure function — no I/O. Tests all routing branches.
  This is the core decision logic of the graph.

TestIrokoGraph
  Full graph execution with all external calls mocked:
    - vector_search (Qdrant)
    - qualify_lead (LLM JSON call)
    - litellm.acompletion (LLM reply generation)
    - book_meeting (calendar stub)
    - escalate_to_human (CRM stub)

  We call build_graph() directly (not get_graph()) to avoid
  the module-level cache and compile a fresh graph per test class.

Why mock the tools here and not use real ones?
  - The graph tests verify state flows correctly between nodes.
  - Tool correctness is verified in test_qualify_lead.py etc.
  - Mixing concerns would make failures hard to diagnose.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.graphs.iroko_graph import (
    AgentState,
    build_graph,
    route_after_qualify,
)

# ─── Shared fixtures ──────────────────────────────────────────────────────────

BASE_STATE: dict[str, Any] = {
    "tenant_id": "00000000-0000-0000-0000-000000000001",
    "instance_id": "1234567",
    "chat_id": "972501234567@c.us",
    "phone_number": "972501234567",
    "sender_name": "Test User",
    "text": "אני מעוניין בהשתלת שיער",
    "id_message": "msg-001",
    "graph_type": "iroko",
    "system_prompt": "You are a helpful sales agent for a hair clinic.",
    "llm_model": "anthropic/claude-sonnet-4-6",
    "qdrant_collection": "iroko_knowledge",
    # initialized empty — nodes fill these in
    "retrieved_context": [],
    "qualification": "undecided",
    "qualification_reason": "",
    "reply_text": "",
    "should_book": False,
    "should_escalate": False,
}

QUALIFY_CONTINUE = {
    "status": "qualified",
    "reason": "Lead is interested",
    "ready_to_book": False,
    "should_escalate": False,
}

QUALIFY_BOOK = {
    "status": "qualified",
    "reason": "Lead is ready to book",
    "ready_to_book": True,
    "should_escalate": False,
}

QUALIFY_ESCALATE = {
    "status": "undecided",
    "reason": "User wants human agent",
    "ready_to_book": False,
    "should_escalate": True,
}


def _llm_response(text: str) -> MagicMock:
    """Build a mock LiteLLM response returning a given text."""
    mock = MagicMock()
    mock.choices[0].message.content = text
    return mock


# ─── route_after_qualify ──────────────────────────────────────────────────────

class TestRouteAfterQualify:
    def test_defaults_to_respond(self):
        """No signals set → continue conversation."""
        state = {**BASE_STATE}
        assert route_after_qualify(state) == "respond"

    def test_should_escalate_routes_to_escalate_human(self):
        state = {**BASE_STATE, "should_escalate": True}
        assert route_after_qualify(state) == "escalate_human"

    def test_should_book_routes_to_book_appointment(self):
        state = {**BASE_STATE, "should_book": True}
        assert route_after_qualify(state) == "book_appointment"

    def test_escalate_takes_priority_over_book(self):
        """If both signals are set, escalate wins (safety first)."""
        state = {**BASE_STATE, "should_escalate": True, "should_book": True}
        assert route_after_qualify(state) == "escalate_human"

    def test_false_values_route_to_respond(self):
        state = {**BASE_STATE, "should_escalate": False, "should_book": False}
        assert route_after_qualify(state) == "respond"


# ─── Full graph tests ─────────────────────────────────────────────────────────

class TestIrokoGraphHappyPath:
    """Tests for the three routing branches: respond / book / escalate."""

    async def test_respond_path_state_flows_correctly(self):
        """
        retrieve → qualify(continue) → respond → END

        Verifies:
          - retrieved_context is set by retrieve node
          - qualification is set by qualify node
          - reply_text is set by respond node
        """
        graph = build_graph()

        with (
            patch(
                "app.services.graphs.iroko_graph.vector_search",
                AsyncMock(return_value=["שאלות נפוצות על השתלת שיער"]),
            ),
            patch(
                "app.services.graphs.iroko_graph.qualify_lead",
                AsyncMock(return_value=QUALIFY_CONTINUE),
            ),
            patch(
                "litellm.acompletion",
                AsyncMock(return_value=_llm_response("תודה על פנייתך! נשמח לעזור.")),
            ),
        ):
            result = await graph.ainvoke(BASE_STATE)

        assert result["retrieved_context"] == ["שאלות נפוצות על השתלת שיער"]
        assert result["qualification"] == "qualified"
        assert result["reply_text"] == "תודה על פנייתך! נשמח לעזור."
        assert result["should_book"] is False
        assert result["should_escalate"] is False

    async def test_book_path_sets_reply_from_booking_tool(self):
        """
        retrieve → qualify(ready_to_book) → book_appointment → END

        Verifies that reply_text comes from book_meeting, not the LLM.
        """
        graph = build_graph()

        with (
            patch(
                "app.services.graphs.iroko_graph.vector_search",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.graphs.iroko_graph.qualify_lead",
                AsyncMock(return_value=QUALIFY_BOOK),
            ),
            patch(
                "app.services.graphs.iroko_graph.book_meeting",
                AsyncMock(return_value={"confirmation_message": "הנה הקישור לתיאום: http://cal.example.com"}),
            ),
        ):
            result = await graph.ainvoke(BASE_STATE)

        assert result["should_book"] is True
        assert result["reply_text"] == "הנה הקישור לתיאום: http://cal.example.com"

    async def test_book_path_does_not_call_llm(self):
        """When booking, the respond node is never reached — no LLM call."""
        graph = build_graph()
        llm_mock = AsyncMock()

        with (
            patch("app.services.graphs.iroko_graph.vector_search", AsyncMock(return_value=[])),
            patch("app.services.graphs.iroko_graph.qualify_lead", AsyncMock(return_value=QUALIFY_BOOK)),
            patch("app.services.graphs.iroko_graph.book_meeting", AsyncMock(return_value={"confirmation_message": "link"})),
            patch("litellm.acompletion", llm_mock),
        ):
            await graph.ainvoke(BASE_STATE)

        llm_mock.assert_not_called()

    async def test_escalate_path_sets_reply_from_escalation_tool(self):
        """
        retrieve → qualify(should_escalate) → escalate_human → END

        Verifies that reply_text comes from escalate_to_human, not the LLM.
        """
        graph = build_graph()

        with (
            patch(
                "app.services.graphs.iroko_graph.vector_search",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.graphs.iroko_graph.qualify_lead",
                AsyncMock(return_value=QUALIFY_ESCALATE),
            ),
            patch(
                "app.services.graphs.iroko_graph.escalate_to_human",
                AsyncMock(return_value={"handoff_message": "נחזור אליך תוך 24 שעות"}),
            ),
        ):
            result = await graph.ainvoke(BASE_STATE)

        assert result["should_escalate"] is True
        assert result["reply_text"] == "נחזור אליך תוך 24 שעות"

    async def test_escalate_path_does_not_call_llm(self):
        """When escalating, the respond node is never reached — no LLM call."""
        graph = build_graph()
        llm_mock = AsyncMock()

        with (
            patch("app.services.graphs.iroko_graph.vector_search", AsyncMock(return_value=[])),
            patch("app.services.graphs.iroko_graph.qualify_lead", AsyncMock(return_value=QUALIFY_ESCALATE)),
            patch("app.services.graphs.iroko_graph.escalate_to_human", AsyncMock(return_value={"handoff_message": "bye"})),
            patch("litellm.acompletion", llm_mock),
        ):
            await graph.ainvoke(BASE_STATE)

        llm_mock.assert_not_called()


class TestIrokoGraphNodeOrdering:
    """Verify that nodes are called in the right order with the right inputs."""

    async def test_retrieve_result_is_passed_to_qualify(self):
        """
        The retrieved_context from node_retrieve must arrive in node_qualify's state.
        We verify this by capturing what qualify_lead receives.
        """
        graph = build_graph()
        captured_context = []

        async def _capture_qualify(text, context, llm_model, system_prompt):
            captured_context.extend(context)
            return QUALIFY_CONTINUE

        with (
            patch(
                "app.services.graphs.iroko_graph.vector_search",
                AsyncMock(return_value=["chunk A", "chunk B"]),
            ),
            patch("app.services.graphs.iroko_graph.qualify_lead", side_effect=_capture_qualify),
            patch("litellm.acompletion", AsyncMock(return_value=_llm_response("ok"))),
        ):
            await graph.ainvoke(BASE_STATE)

        assert captured_context == ["chunk A", "chunk B"]

    async def test_user_text_is_passed_to_qualify(self):
        """qualify_lead must receive the original user message."""
        graph = build_graph()
        captured_text = []

        async def _capture(text, context, llm_model, system_prompt):
            captured_text.append(text)
            return QUALIFY_CONTINUE

        with (
            patch("app.services.graphs.iroko_graph.vector_search", AsyncMock(return_value=[])),
            patch("app.services.graphs.iroko_graph.qualify_lead", side_effect=_capture),
            patch("litellm.acompletion", AsyncMock(return_value=_llm_response("ok"))),
        ):
            await graph.ainvoke({**BASE_STATE, "text": "כמה עולה השתלה?"})

        assert captured_text == ["כמה עולה השתלה?"]


class TestIrokoGraphResilience:
    """Verify the graph doesn't crash on tool failures."""

    async def test_qdrant_down_graph_continues_with_empty_context(self):
        """
        vector_search already returns [] on error (see tools/vector_search.py).
        The graph must handle [] gracefully and still produce a reply.
        """
        graph = build_graph()

        with (
            patch("app.services.graphs.iroko_graph.vector_search", AsyncMock(return_value=[])),
            patch("app.services.graphs.iroko_graph.qualify_lead", AsyncMock(return_value=QUALIFY_CONTINUE)),
            patch("litellm.acompletion", AsyncMock(return_value=_llm_response("שלום!"))),
        ):
            result = await graph.ainvoke(BASE_STATE)

        assert result["retrieved_context"] == []
        assert result["reply_text"] == "שלום!"
