"""
Green API HTTP client — send WhatsApp messages via the Green API REST API.

Green API endpoint format:
  POST https://api.green-api.com/waInstance{instance_id}/sendMessage/{token}
  Body: {"chatId": "<phone>@c.us", "message": "<text>"}

Why a plain httpx client (not a SDK)?
  The Green API Python SDK is not async-native.
  httpx is already in our dependency tree (via FastAPI) and is fully async.
  The API surface we need is just one endpoint — no need for a full SDK.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

GREEN_API_BASE = "https://api.green-api.com"


class GreenAPIClient:
    """Thin async wrapper around the Green API sendMessage endpoint."""

    def __init__(self, instance_id: str, token: str):
        self.instance_id = instance_id
        self.token = token
        self._base = f"{GREEN_API_BASE}/waInstance{instance_id}"

    def _url(self, method: str) -> str:
        return f"{self._base}/{method}/{self.token}"

    async def send_message(self, chat_id: str, text: str) -> dict:
        """
        Send a text message to a WhatsApp chat.

        Args:
            chat_id: WhatsApp chat ID (e.g. "972501234567@c.us")
            text:    Message text (plain text; WhatsApp basic markdown is supported)

        Returns:
            Green API response dict (contains idMessage on success).

        Raises:
            httpx.HTTPStatusError: On 4xx/5xx from Green API.
            httpx.TimeoutException:  If Green API doesn't respond in time.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self._url("sendMessage"),
                json={"chatId": chat_id, "message": text},
            )
            response.raise_for_status()
            data = response.json()

        logger.info(
            "greenapi:sent instance=%s chat=%s id_message=%s",
            self.instance_id,
            chat_id,
            data.get("idMessage", "?"),
        )
        return data
