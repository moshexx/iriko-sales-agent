"""
Escalation tool — hand the conversation off to a human agent.

What this does:
  1. Update the lead's CRM status to "escalated" (currently: Postgres stub).
  2. Return the handoff message text to send to the user.
  3. (Future) Notify the human agent via Slack/email.

CRM stub:
  In Phase 3, the CRM update is logged but not persisted (TODO).
  Phase 4 will introduce the CRM adapter layer (Postgres for Iroko, Biznness for DNG).

Handoff message:
  Hardcoded in Hebrew for now (Iroko is an Israeli clinic).
  Phase 7 will make this configurable per tenant in the DB.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# The message sent to the user when we escalate.
# Phase 7: move to tenant config in DB.
HANDOFF_MESSAGE = "הבקשה הועברה לנציג שלנו. נחזור אליך תוך 24 שעות בימי עסקים."


async def escalate_to_human(
    tenant_id: str,
    phone_number: str,
    reason: str,
) -> dict[str, Any]:
    """
    Escalate the conversation to a human agent.

    Args:
        tenant_id:    UUID of the tenant (for CRM update).
        phone_number: The lead's phone number.
        reason:       Why we're escalating (for the CRM log).

    Returns:
        {"handoff_message": str}  — the text to send to the user.
    """
    logger.info(
        "escalate tenant=%s phone=%s reason=%s",
        tenant_id,
        phone_number,
        reason,
    )

    # TODO Phase 4: update CRM status
    # await crm_adapter.update_status(
    #     tenant_id=tenant_id,
    #     phone_number=phone_number,
    #     status="escalated",
    #     note=reason,
    # )

    return {"handoff_message": HANDOFF_MESSAGE}
