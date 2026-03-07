"""
Pydantic schemas for Green API webhook payloads.

Green API sends different event types (typeWebhook):
- incomingMessageReceived  ← the main one we care about
- outgoingMessageReceived  ← our own sent messages (ignore)
- stateInstanceChanged     ← Green API instance status (ignore for now)
- incomingCall             ← calls (ignore)

Reference: https://green-api.com/en/docs/api/receiving/notifications-format/
"""

from typing import Any

from pydantic import BaseModel, Field


class InstanceData(BaseModel):
    id_instance: int = Field(alias="idInstance")
    wid: str  # WhatsApp ID of the instance number
    type_instance: str = Field(alias="typeInstance")

    model_config = {"populate_by_name": True}


class SenderData(BaseModel):
    chat_id: str = Field(alias="chatId")          # e.g. "972501234567@c.us" or "group@g.us"
    sender: str                                    # sender's WhatsApp ID
    sender_name: str = Field(alias="senderName", default="")

    model_config = {"populate_by_name": True}


class TextMessageData(BaseModel):
    text_message: str = Field(alias="textMessage", default="")

    model_config = {"populate_by_name": True}


class ExtendedTextMessageData(BaseModel):
    text: str = Field(default="")
    description: str = Field(default="")
    jpeg_thumbnail: str = Field(alias="jpegThumbnail", default="")

    model_config = {"populate_by_name": True}


class ImageMessageData(BaseModel):
    url_file: str = Field(alias="urlFile", default="")
    caption: str = Field(default="")

    model_config = {"populate_by_name": True}


class MessageData(BaseModel):
    type_message: str = Field(alias="typeMessage")
    # Only one of these will be populated depending on typeMessage
    text_message_data: TextMessageData | None = Field(alias="textMessageData", default=None)
    extended_text_message_data: ExtendedTextMessageData | None = Field(
        alias="extendedTextMessageData", default=None
    )
    image_message_data: ImageMessageData | None = Field(alias="imageMessageData", default=None)

    model_config = {"populate_by_name": True}

    def extract_text(self) -> str:
        """Extract plain text from any message type."""
        if self.text_message_data:
            return self.text_message_data.text_message
        if self.extended_text_message_data:
            return self.extended_text_message_data.text
        if self.image_message_data:
            return self.image_message_data.caption
        return ""


class GreenAPIWebhook(BaseModel):
    """
    Top-level Green API webhook payload.
    The instance_id comes from the URL path, not the body.
    """

    type_webhook: str = Field(alias="typeWebhook")
    instance_data: InstanceData = Field(alias="instanceData")
    timestamp: int
    id_message: str = Field(alias="idMessage")
    sender_data: SenderData | None = Field(alias="senderData", default=None)
    message_data: MessageData | None = Field(alias="messageData", default=None)

    # Extra fields we don't need but must accept
    model_config = {"populate_by_name": True, "extra": "allow"}

    @property
    def is_incoming(self) -> bool:
        return self.type_webhook == "incomingMessageReceived"

    @property
    def is_group_message(self) -> bool:
        if not self.sender_data:
            return False
        return self.sender_data.chat_id.endswith("@g.us")

    @property
    def chat_id(self) -> str:
        return self.sender_data.chat_id if self.sender_data else ""

    @property
    def phone_number(self) -> str:
        """Extract bare phone number from chatId (e.g. '972501234567@c.us' → '972501234567')."""
        return self.chat_id.split("@")[0]
