"""
Booking tool — schedule a consultation appointment for a qualified lead.

Flow:
  1. Create (or update) the lead record in the CRM.
  2. Generate a calendar booking link.
  3. Return the confirmation message with the link.

Phase 3 stub:
  No real calendar or CRM integration yet. Returns a placeholder message.

Phase 4 will add:
  - Iroko: internal Postgres calendar + availability check
  - DNG (Phase 6): Biznness API calendar integration

The confirmation message is in Hebrew (Iroko is an Israeli clinic).
Phase 7: move message templates to tenant config in DB.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def book_meeting(
    tenant_id: str,
    phone_number: str,
    sender_name: str,
) -> dict[str, Any]:
    """
    Book a consultation appointment for a qualified lead.

    Args:
        tenant_id:    UUID of the tenant (for CRM lookup).
        phone_number: The lead's phone number.
        sender_name:  The lead's name (for personalization).

    Returns:
        {"confirmation_message": str}  — the text to send to the user.
    """
    logger.info(
        "book_meeting tenant=%s phone=%s name=%s",
        tenant_id,
        phone_number,
        sender_name,
    )

    # TODO Phase 4: real calendar integration
    # slot = await calendar.find_next_available(tenant_id)
    # booking = await calendar.create_booking(slot, phone_number, sender_name)
    # link = booking.calendar_link

    # Phase 3: stub — returns placeholder link
    link = "https://cal.leadwise.ai/book"  # placeholder

    name_part = f" {sender_name}" if sender_name else ""
    message = (
        f"מעולה{name_part}! 🎉\n"
        f"לתיאום ייעוץ ראשוני, לחץ על הקישור:\n{link}\n\n"
        f"נשמח לראות אותך בקרוב!"
    )

    return {"confirmation_message": message}
