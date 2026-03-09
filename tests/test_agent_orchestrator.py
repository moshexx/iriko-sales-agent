"""
Unit tests for the agent orchestrator (app/services/agent_orchestrator.py).

Strategy: mock everything external.
  - get_graph() → mock compiled graph
  - DB session → mock that returns a fake Tenant
  - _send_reply → mock (we don't want to call Green API)

We're testing orchestrator WIRING, not the graph or tools:
  1. Does it call the correct graph (by graph_type)?
  2. Does it pass the right initial state to the graph?
  3. Does it send the reply when graph produces reply_text?
  4. Does it skip sending when reply_text is empty?
  5. Does it raise if the tenant no longer exists in the DB?
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_orchestrator import run_agent

TENANT_ID = "00000000-0000-0000-0000-000000000042"

BASE_PAYLOAD: dict[str, Any] = {
    "tenant_id": TENANT_ID,
    "instance_id": "1234567",
    "graph_type": "iroko",
    "chat_id": "972501234567@c.us",
    "phone_number": "972501234567",
    "sender_name": "Test User",
    "text": "שלום",
    "id_message": "msg-001",
    "token_ref": "test-token-abc",
}


def _make_tenant(
    slug: str = "iroko",
    system_prompt: str = "You are a sales agent",
    llm_model: str = "anthropic/claude-sonnet-4-6",
    qdrant_collection: str = "iroko_knowledge",
) -> MagicMock:
    tenant = MagicMock()
    tenant.id = uuid.UUID(TENANT_ID)
    tenant.slug = slug
    tenant.system_prompt = system_prompt
    tenant.llm_model = llm_model
    tenant.qdrant_collection = qdrant_collection
    return tenant


def _make_db(tenant: MagicMock | None = None) -> AsyncMock:
    """Build a mock AsyncSession that returns the given tenant from .execute()."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = tenant
    db.execute = AsyncMock(return_value=result)
    return db


def _make_graph_mock(reply_text: str = "תודה!") -> MagicMock:
    """Build a mock compiled LangGraph that returns a state with the given reply."""
    graph = MagicMock()
    graph.ainvoke = AsyncMock(
        return_value={
            **BASE_PAYLOAD,
            "reply_text": reply_text,
            "retrieved_context": [],
            "qualification": "qualified",
            "qualification_reason": "interested",
            "should_book": False,
            "should_escalate": False,
        }
    )
    return graph


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestRunAgentGraphSelection:
    async def test_calls_graph_with_correct_graph_type(self):
        """get_graph must be called with the payload's graph_type."""
        mock_graph = _make_graph_mock()

        with (
            patch("app.services.agent_orchestrator.get_graph", return_value=mock_graph) as mock_factory,
            patch("app.services.agent_orchestrator._send_reply", AsyncMock()),
        ):
            await run_agent(BASE_PAYLOAD, _make_db(_make_tenant()))

        mock_factory.assert_called_once_with("iroko")

    async def test_graph_receives_text_from_payload(self):
        mock_graph = _make_graph_mock()

        with (
            patch("app.services.agent_orchestrator.get_graph", return_value=mock_graph),
            patch("app.services.agent_orchestrator._send_reply", AsyncMock()),
        ):
            await run_agent({**BASE_PAYLOAD, "text": "כמה עולה השתלה?"}, _make_db(_make_tenant()))

        call_state = mock_graph.ainvoke.call_args[0][0]
        assert call_state["text"] == "כמה עולה השתלה?"

    async def test_graph_receives_tenant_system_prompt(self):
        """Tenant's system_prompt from DB must be injected into the state."""
        mock_graph = _make_graph_mock()
        tenant = _make_tenant(system_prompt="Custom persona for Iroko")

        with (
            patch("app.services.agent_orchestrator.get_graph", return_value=mock_graph),
            patch("app.services.agent_orchestrator._send_reply", AsyncMock()),
        ):
            await run_agent(BASE_PAYLOAD, _make_db(tenant))

        call_state = mock_graph.ainvoke.call_args[0][0]
        assert call_state["system_prompt"] == "Custom persona for Iroko"

    async def test_graph_receives_tenant_llm_model(self):
        mock_graph = _make_graph_mock()
        tenant = _make_tenant(llm_model="openai/gpt-4o")

        with (
            patch("app.services.agent_orchestrator.get_graph", return_value=mock_graph),
            patch("app.services.agent_orchestrator._send_reply", AsyncMock()),
        ):
            await run_agent(BASE_PAYLOAD, _make_db(tenant))

        call_state = mock_graph.ainvoke.call_args[0][0]
        assert call_state["llm_model"] == "openai/gpt-4o"

    async def test_graph_receives_qdrant_collection(self):
        mock_graph = _make_graph_mock()
        tenant = _make_tenant(qdrant_collection="iroko_faq_v2")

        with (
            patch("app.services.agent_orchestrator.get_graph", return_value=mock_graph),
            patch("app.services.agent_orchestrator._send_reply", AsyncMock()),
        ):
            await run_agent(BASE_PAYLOAD, _make_db(tenant))

        call_state = mock_graph.ainvoke.call_args[0][0]
        assert call_state["qdrant_collection"] == "iroko_faq_v2"


class TestRunAgentReplySending:
    async def test_sends_reply_when_graph_produces_text(self):
        mock_send = AsyncMock()
        mock_graph = _make_graph_mock(reply_text="נשמח לעזור!")

        with (
            patch("app.services.agent_orchestrator.get_graph", return_value=mock_graph),
            patch("app.services.agent_orchestrator._send_reply", mock_send),
        ):
            await run_agent(BASE_PAYLOAD, _make_db(_make_tenant()))

        mock_send.assert_called_once()

    async def test_reply_is_sent_to_correct_chat_id(self):
        mock_send = AsyncMock()
        mock_graph = _make_graph_mock(reply_text="שלום!")

        with (
            patch("app.services.agent_orchestrator.get_graph", return_value=mock_graph),
            patch("app.services.agent_orchestrator._send_reply", mock_send),
        ):
            await run_agent(BASE_PAYLOAD, _make_db(_make_tenant()))

        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["chat_id"] == "972501234567@c.us"
        assert call_kwargs["text"] == "שלום!"

    async def test_does_not_send_when_reply_text_is_empty(self):
        """If the graph produces no reply, we must not send an empty message."""
        mock_send = AsyncMock()
        mock_graph = _make_graph_mock(reply_text="")

        with (
            patch("app.services.agent_orchestrator.get_graph", return_value=mock_graph),
            patch("app.services.agent_orchestrator._send_reply", mock_send),
        ):
            await run_agent(BASE_PAYLOAD, _make_db(_make_tenant()))

        mock_send.assert_not_called()


class TestRunAgentTenantLookup:
    async def test_raises_if_tenant_not_in_db(self):
        """
        Tenant was deleted between ingress and worker execution.
        Must raise ValueError — ARQ will retry the job.
        """
        with (
            patch("app.services.agent_orchestrator.get_graph", MagicMock()),
        ):
            with pytest.raises(ValueError, match="not found"):
                await run_agent(BASE_PAYLOAD, _make_db(tenant=None))

    async def test_uses_default_system_prompt_when_none_in_db(self):
        """Tenant has no system_prompt set — must fall back to the default."""
        mock_graph = _make_graph_mock()
        tenant = _make_tenant(system_prompt=None)  # type: ignore[arg-type]

        with (
            patch("app.services.agent_orchestrator.get_graph", return_value=mock_graph),
            patch("app.services.agent_orchestrator._send_reply", AsyncMock()),
        ):
            await run_agent(BASE_PAYLOAD, _make_db(tenant))

        call_state = mock_graph.ainvoke.call_args[0][0]
        # Must be a non-empty string (the default)
        assert isinstance(call_state["system_prompt"], str)
        assert len(call_state["system_prompt"]) > 0

    async def test_uses_default_llm_model_when_none_in_db(self):
        mock_graph = _make_graph_mock()
        tenant = _make_tenant(llm_model=None)  # type: ignore[arg-type]

        with (
            patch("app.services.agent_orchestrator.get_graph", return_value=mock_graph),
            patch("app.services.agent_orchestrator._send_reply", AsyncMock()),
        ):
            await run_agent(BASE_PAYLOAD, _make_db(tenant))

        call_state = mock_graph.ainvoke.call_args[0][0]
        assert "claude" in call_state["llm_model"]  # default is Claude Sonnet
