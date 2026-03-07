"""
Iroko LangGraph agent graph.

Conversation flow:
  retrieve → qualify → respond → (END | book_appointment | escalate_human)

Node responsibilities:
  retrieve          Search Qdrant for relevant knowledge (FAQ, treatments, pricing).
  qualify           Determine if the lead is worth pursuing.
                    If clearly disqualified → route to escalate.
                    If ready to book → route to book_appointment.
                    Otherwise → respond (keep conversation going).
  respond           Generate and send the LLM reply to the user.
  book_appointment  Trigger the booking tool, send confirmation.
  escalate_human    Mark lead as escalated in CRM, send handoff message.

State:
  AgentState is a TypedDict — LangGraph passes it between nodes.
  Each node receives the full state and returns the fields it modified.

LangGraph concepts used here:
  - StateGraph: a graph where each node reads+writes a shared state dict
  - add_node / add_edge / add_conditional_edges: define the flow
  - compile(): turns the builder into an executable runnable
  - ainvoke(): async execution of the full graph
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from app.services.tools.book_meeting import book_meeting
from app.services.tools.escalate import escalate_to_human
from app.services.tools.qualify_lead import qualify_lead
from app.services.tools.vector_search import vector_search

logger = logging.getLogger(__name__)


# ─── State ────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    """
    The shared state that flows between all nodes in the Iroko graph.

    Every node receives this state and returns a dict with the fields it updated.
    LangGraph merges the returned dict into the state automatically.
    """
    # ── Input (set by orchestrator, read-only in nodes) ──
    tenant_id: str
    instance_id: str
    chat_id: str
    phone_number: str
    sender_name: str
    text: str                      # the user's message text
    id_message: str
    graph_type: str
    system_prompt: str
    llm_model: str                 # e.g. "anthropic/claude-sonnet-4-6"
    qdrant_collection: str

    # ── Loaded by orchestrator before graph runs ──
    chat_history: list[dict]       # [{role, content}, ...] ordered oldest-first

    # ── Set by retrieve node ──
    retrieved_context: list[str]   # relevant chunks from Qdrant

    # ── Set by qualify node ──
    qualification: Literal["qualified", "disqualified", "undecided"]
    qualification_reason: str

    # ── Set by respond node ──
    reply_text: str                # the text we'll send back to the user

    # ── Routing signals ──
    should_book: bool              # qualify decided the lead is ready to book
    should_escalate: bool          # qualify or respond decided to escalate


# ─── Nodes ────────────────────────────────────────────────────────────────────

async def node_retrieve(state: AgentState) -> dict[str, Any]:
    """
    Search the tenant's Qdrant collection for relevant knowledge.

    Returns: retrieved_context — list of relevant text chunks.
    """
    logger.info("iroko:retrieve chat=%s", state["chat_id"])

    chunks = await vector_search(
        query=state["text"],
        collection=state["qdrant_collection"],
        top_k=5,
    )

    return {"retrieved_context": chunks}


async def node_qualify(state: AgentState) -> dict[str, Any]:
    """
    Decide if the lead should be qualified, disqualified, or needs more info.

    Returns qualification + routing signals.
    """
    logger.info("iroko:qualify chat=%s", state["chat_id"])

    result = await qualify_lead(
        text=state["text"],
        context=state["retrieved_context"],
        llm_model=state["llm_model"],
        system_prompt=state["system_prompt"],
    )

    return {
        "qualification": result["status"],
        "qualification_reason": result["reason"],
        "should_book": result["ready_to_book"],
        "should_escalate": result["should_escalate"],
    }


async def node_respond(state: AgentState) -> dict[str, Any]:
    """
    Generate the LLM reply using the full conversation context.

    Prompt structure:
      system: persona + relevant knowledge base chunks
      [history]: past turns from Postgres (oldest-first)
      user: the current message

    Including history lets the LLM say "as you mentioned earlier..."
    and continue qualification across multiple turns naturally.
    """
    import litellm

    logger.info("iroko:respond chat=%s history_len=%d", state["chat_id"], len(state.get("chat_history", [])))

    context_block = "\n\n".join(state["retrieved_context"]) if state["retrieved_context"] else ""

    system_content = state["system_prompt"]
    if context_block:
        system_content += f"\n\n## Relevant Knowledge\n{context_block}"

    # Build the message list: system + history + current user message
    messages: list[dict] = [{"role": "system", "content": system_content}]
    messages.extend(state.get("chat_history", []))  # past turns (may be empty for first message)
    messages.append({"role": "user", "content": state["text"]})

    response = await litellm.acompletion(
        model=state["llm_model"],
        messages=messages,
        max_tokens=512,
        temperature=0.3,
    )

    reply = response.choices[0].message.content or ""
    return {"reply_text": reply}


async def node_book_appointment(state: AgentState) -> dict[str, Any]:
    """
    Trigger the booking tool and set reply_text to the confirmation message.
    """
    logger.info("iroko:book chat=%s", state["chat_id"])

    result = await book_meeting(
        tenant_id=state["tenant_id"],
        phone_number=state["phone_number"],
        sender_name=state["sender_name"],
    )

    return {"reply_text": result["confirmation_message"]}


async def node_escalate(state: AgentState) -> dict[str, Any]:
    """
    Mark the lead as escalated in the CRM and set reply_text to the handoff message.
    """
    logger.info("iroko:escalate chat=%s", state["chat_id"])

    result = await escalate_to_human(
        tenant_id=state["tenant_id"],
        phone_number=state["phone_number"],
        reason=state.get("qualification_reason", "user requested"),
    )

    return {"reply_text": result["handoff_message"]}


# ─── Routing ──────────────────────────────────────────────────────────────────

def route_after_qualify(state: AgentState) -> str:
    """
    Conditional edge: decide what happens after the qualify node.

    Returns the name of the next node.
    """
    if state.get("should_escalate"):
        return "escalate_human"
    if state.get("should_book"):
        return "book_appointment"
    return "respond"


# ─── Graph builder ────────────────────────────────────────────────────────────

def build_graph():
    """
    Build and compile the Iroko LangGraph state machine.

    Called once by the factory, result is cached.
    """
    builder = StateGraph(AgentState)

    # Register nodes
    builder.add_node("retrieve", node_retrieve)
    builder.add_node("qualify", node_qualify)
    builder.add_node("respond", node_respond)
    builder.add_node("book_appointment", node_book_appointment)
    builder.add_node("escalate_human", node_escalate)

    # Entry point
    builder.set_entry_point("retrieve")

    # Linear edges
    builder.add_edge("retrieve", "qualify")

    # Conditional routing after qualify
    builder.add_conditional_edges(
        "qualify",
        route_after_qualify,
        {
            "respond": "respond",
            "book_appointment": "book_appointment",
            "escalate_human": "escalate_human",
        },
    )

    # All terminal nodes end the graph
    builder.add_edge("respond", END)
    builder.add_edge("book_appointment", END)
    builder.add_edge("escalate_human", END)

    return builder.compile()
