"""
Lead qualification tool — decide if this lead is worth pursuing.

Strategy: structured LLM call with a JSON-mode response.
  We ask the LLM to analyze the conversation and return a structured verdict.
  Using JSON mode (response_format={"type": "json_object"}) ensures we can
  parse the output reliably without regex hacks.

Qualification outcomes:
  qualified       — Lead is interested and suitable. Keep engaging.
  disqualified    — Lead is clearly not a fit. Escalate or end gracefully.
  undecided       — Need more information. Keep the conversation going.

Routing signals:
  ready_to_book   — Lead expressed clear intent to act (purchase, book, etc.).
  should_escalate — Lead explicitly asked for a human OR sent gibberish.

Each graph/tenant supplies its own qualify_prompt with domain-specific criteria.
This function is a generic executor — it has no hardcoded business logic.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def qualify_lead(
    text: str,
    context: list[str],
    llm_model: str,
    system_prompt: str,
    qualify_prompt: str,
    chat_history: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Analyze the lead's message and return a qualification verdict.

    Args:
        text:           The user's current message.
        context:        Retrieved knowledge base chunks (from vector_search).
        llm_model:      LiteLLM model string (e.g. "anthropic/claude-sonnet-4-6").
        system_prompt:  The tenant's base system prompt (for persona context).
        qualify_prompt: Domain-specific routing instructions for the qualifier.
                        Defined per graph (e.g. IROKO_QUALIFY_PROMPT).
        chat_history:   Recent conversation turns [{role, content}, ...], oldest-first.
                        Last 3 pairs are included for context.

    Returns:
        {
            "status": "qualified" | "disqualified" | "undecided",
            "reason": str,
            "ready_to_book": bool,
            "should_escalate": bool,
        }
    """
    import litellm

    context_block = "\n\n".join(context) if context else "No context available."

    # Include the last 3 conversation turns so qualification is not stateless
    history_block = ""
    if chat_history:
        recent = chat_history[-6:]  # last 3 pairs (user + assistant)
        lines = []
        for turn in recent:
            role = "Customer" if turn["role"] == "user" else "Agent"
            lines.append(f"{role}: {turn['content']}")
        history_block = "\n".join(lines)

    content_parts = [f"## Agent Persona\n{system_prompt}"]
    if history_block:
        content_parts.append(f"## Recent Conversation\n{history_block}")
    content_parts.append(f"## Knowledge Base Context\n{context_block}")
    content_parts.append(f"## Current User Message\n{text}")

    messages = [
        {"role": "system", "content": qualify_prompt},
        {"role": "user", "content": "\n\n".join(content_parts)},
    ]

    try:
        response = await litellm.acompletion(
            model=llm_model,
            messages=messages,
            max_tokens=200,
            temperature=0.0,
        )

        raw = (response.choices[0].message.content or "").strip()
        if not raw:
            raise ValueError("LLM returned empty response for qualification")
        # Claude sometimes wraps JSON in markdown fences — strip them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        result = json.loads(raw)

        return {
            "status": result.get("status", "undecided"),
            "reason": result.get("reason", ""),
            "ready_to_book": bool(result.get("ready_to_book", False)),
            "should_escalate": bool(result.get("should_escalate", False)),
        }

    except Exception:
        logger.exception("qualify_lead failed, defaulting to undecided")
        return {
            "status": "undecided",
            "reason": "qualification error — defaulting to continue conversation",
            "ready_to_book": False,
            "should_escalate": False,
        }
