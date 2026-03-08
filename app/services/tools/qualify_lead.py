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
  ready_to_book   — Lead has expressed intent to book AND is qualified.
  should_escalate — Lead explicitly asked for human OR responded with gibberish 2x.

Phase 4 will add:
  - Chat history in the prompt (not just the current message)
  - Tracking gibberish/human-request count in Postgres
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

QUALIFY_SYSTEM_PROMPT = """\
You are a lead qualification assistant for a hair clinic sales agent.

Given a user's message and relevant knowledge base context, determine:
1. Is this lead qualified (genuinely interested, suitable for treatment)?
2. Are they ready to book a consultation appointment?
3. Should we escalate to a human agent?

Return ONLY valid JSON in this exact format:
{
  "status": "qualified" | "disqualified" | "undecided",
  "reason": "<one sentence explanation>",
  "ready_to_book": true | false,
  "should_escalate": true | false
}

Escalate if:
- The user explicitly asks for a human agent
- The message is complete gibberish or clearly not related to hair treatment

Disqualify if:
- The user clearly states they are not interested
- The user has a condition that is clearly incompatible (e.g., full baldness, active cancer)
"""


async def qualify_lead(
    text: str,
    context: list[str],
    llm_model: str,
    system_prompt: str,
) -> dict[str, Any]:
    """
    Analyze the lead's message and return a qualification verdict.

    Args:
        text:          The user's current message.
        context:       Retrieved knowledge base chunks (from vector_search).
        llm_model:     LiteLLM model string (e.g. "anthropic/claude-sonnet-4-6").
        system_prompt: The tenant's base system prompt (for persona).

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

    messages = [
        {"role": "system", "content": QUALIFY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"## Knowledge Base Context\n{context_block}\n\n"
                f"## User Message\n{text}"
            ),
        },
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

        # Validate required fields with safe defaults
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
