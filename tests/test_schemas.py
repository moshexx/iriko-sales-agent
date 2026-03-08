"""
Unit tests for GreenAPIWebhook Pydantic schema.

These are pure unit tests — no DB, no Redis, no network.
They verify that we parse Green API payloads correctly and extract the right data.

Why this matters: if our schema is wrong, every message is silently misread.
"""


from app.schemas.greenapi import GreenAPIWebhook
from tests.fixtures.greenapi_payloads import (
    group_message,
    image_message_no_caption,
    image_message_with_caption,
    incoming_extended_text,
    incoming_text,
    outgoing_message,
    state_change,
)


class TestParsing:
    def test_parse_incoming_text(self):
        payload = incoming_text(text="שלום", id_message="msg-001", chat_id="972501111111@c.us")
        event = GreenAPIWebhook.model_validate(payload)

        assert event.type_webhook == "incomingMessageReceived"
        assert event.id_message == "msg-001"
        assert event.sender_data.chat_id == "972501111111@c.us"
        assert event.sender_data.sender_name == "Test User"
        assert event.instance_data.id_instance == 1234567

    def test_parse_outgoing_message(self):
        event = GreenAPIWebhook.model_validate(outgoing_message())
        assert event.type_webhook == "outgoingMessageReceived"

    def test_parse_group_message(self):
        event = GreenAPIWebhook.model_validate(group_message())
        assert event.sender_data.chat_id.endswith("@g.us")

    def test_parse_state_change_no_sender(self):
        """State change events have no senderData — must not crash."""
        event = GreenAPIWebhook.model_validate(state_change())
        assert event.sender_data is None
        assert event.message_data is None

    def test_extra_fields_are_allowed(self):
        """Green API may add new fields — we must not crash on unknown fields."""
        payload = incoming_text()
        payload["someNewFieldFromGreenAPI"] = "surprise"
        event = GreenAPIWebhook.model_validate(payload)  # should not raise
        assert event is not None


class TestIsIncoming:
    def test_incoming_text_is_incoming(self):
        event = GreenAPIWebhook.model_validate(incoming_text())
        assert event.is_incoming is True

    def test_outgoing_is_not_incoming(self):
        event = GreenAPIWebhook.model_validate(outgoing_message())
        assert event.is_incoming is False

    def test_state_change_is_not_incoming(self):
        event = GreenAPIWebhook.model_validate(state_change())
        assert event.is_incoming is False


class TestIsGroupMessage:
    def test_group_chat_is_group(self):
        event = GreenAPIWebhook.model_validate(group_message())
        assert event.is_group_message is True

    def test_personal_chat_is_not_group(self):
        event = GreenAPIWebhook.model_validate(incoming_text())
        assert event.is_group_message is False

    def test_no_sender_data_is_not_group(self):
        event = GreenAPIWebhook.model_validate(state_change())
        assert event.is_group_message is False


class TestPhoneNumber:
    def test_extracts_phone_from_chat_id(self):
        event = GreenAPIWebhook.model_validate(
            incoming_text(chat_id="972501234567@c.us")
        )
        assert event.phone_number == "972501234567"

    def test_group_phone_extraction(self):
        """Groups have a different format — still extracts the part before @."""
        event = GreenAPIWebhook.model_validate(group_message())
        assert "@" not in event.phone_number


class TestExtractText:
    def test_text_message(self):
        payload = incoming_text(text="שלום, מה שלומך?")
        event = GreenAPIWebhook.model_validate(payload)
        assert event.message_data.extract_text() == "שלום, מה שלומך?"

    def test_extended_text_message(self):
        payload = incoming_extended_text(text="כמה עולה השתלת שיער?")
        event = GreenAPIWebhook.model_validate(payload)
        assert event.message_data.extract_text() == "כמה עולה השתלת שיער?"

    def test_image_with_caption(self):
        payload = image_message_with_caption(caption="הנה תמונה")
        event = GreenAPIWebhook.model_validate(payload)
        assert event.message_data.extract_text() == "הנה תמונה"

    def test_image_without_caption_returns_empty(self):
        payload = image_message_no_caption()
        event = GreenAPIWebhook.model_validate(payload)
        assert event.message_data.extract_text() == ""

    def test_no_message_data_returns_empty(self):
        event = GreenAPIWebhook.model_validate(state_change())
        # state_change has no messageData
        assert event.message_data is None
