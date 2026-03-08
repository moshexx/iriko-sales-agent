"""
Sample Green API webhook payloads for testing.

These mirror the real payloads documented at:
https://green-api.com/en/docs/api/receiving/notifications-format/

Each fixture is a plain dict (as received from the HTTP request body).
"""


def incoming_text(
    instance_id: int = 1234567,
    chat_id: str = "972501234567@c.us",
    sender_name: str = "Test User",
    text: str = "שלום, אני מעוניין בהשתלת שיער",
    id_message: str = "msg-001",
    timestamp: int = 1700000000,
) -> dict:
    """Standard inbound text message — the happy path."""
    return {
        "typeWebhook": "incomingMessageReceived",
        "instanceData": {
            "idInstance": instance_id,
            "wid": "972555000000@c.us",
            "typeInstance": "whatsapp",
        },
        "timestamp": timestamp,
        "idMessage": id_message,
        "senderData": {
            "chatId": chat_id,
            "sender": chat_id,
            "senderName": sender_name,
        },
        "messageData": {
            "typeMessage": "textMessage",
            "textMessageData": {
                "textMessage": text,
            },
        },
    }


def incoming_extended_text(
    text: str = "פרטים נוספים על הייעוץ",
    id_message: str = "msg-002",
) -> dict:
    """Extended text message (links, quoted messages) — same as text but different field."""
    return {
        "typeWebhook": "incomingMessageReceived",
        "instanceData": {
            "idInstance": 1234567,
            "wid": "972555000000@c.us",
            "typeInstance": "whatsapp",
        },
        "timestamp": 1700000001,
        "idMessage": id_message,
        "senderData": {
            "chatId": "972501234567@c.us",
            "sender": "972501234567@c.us",
            "senderName": "Test User",
        },
        "messageData": {
            "typeMessage": "extendedTextMessage",
            "extendedTextMessageData": {
                "text": text,
                "description": "",
                "jpegThumbnail": "",
            },
        },
    }


def outgoing_message(id_message: str = "msg-out-001") -> dict:
    """Message sent by us — should be filtered out."""
    return {
        "typeWebhook": "outgoingMessageReceived",
        "instanceData": {
            "idInstance": 1234567,
            "wid": "972555000000@c.us",
            "typeInstance": "whatsapp",
        },
        "timestamp": 1700000002,
        "idMessage": id_message,
        "senderData": {
            "chatId": "972501234567@c.us",
            "sender": "972555000000@c.us",
            "senderName": "Maya Bot",
        },
        "messageData": {
            "typeMessage": "textMessage",
            "textMessageData": {"textMessage": "תודה על פנייתך!"},
        },
    }


def group_message(id_message: str = "msg-grp-001") -> dict:
    """Message from a WhatsApp group — should be filtered out."""
    return {
        "typeWebhook": "incomingMessageReceived",
        "instanceData": {
            "idInstance": 1234567,
            "wid": "972555000000@c.us",
            "typeInstance": "whatsapp",
        },
        "timestamp": 1700000003,
        "idMessage": id_message,
        "senderData": {
            "chatId": "972501234567-1234567890@g.us",  # group chat ID ends with @g.us
            "sender": "972501234567@c.us",
            "senderName": "Group Member",
        },
        "messageData": {
            "typeMessage": "textMessage",
            "textMessageData": {"textMessage": "הי לכולם"},
        },
    }


def image_message_no_caption(id_message: str = "msg-img-001") -> dict:
    """Image with no caption — extract_text returns empty string, should be filtered."""
    return {
        "typeWebhook": "incomingMessageReceived",
        "instanceData": {
            "idInstance": 1234567,
            "wid": "972555000000@c.us",
            "typeInstance": "whatsapp",
        },
        "timestamp": 1700000004,
        "idMessage": id_message,
        "senderData": {
            "chatId": "972501234567@c.us",
            "sender": "972501234567@c.us",
            "senderName": "Test User",
        },
        "messageData": {
            "typeMessage": "imageMessage",
            "imageMessageData": {
                "urlFile": "https://example.com/image.jpg",
                "caption": "",
            },
        },
    }


def image_message_with_caption(
    caption: str = "הנה תמונה של ראשי",
    id_message: str = "msg-img-cap-001",
) -> dict:
    """Image with caption — caption is the text to process."""
    return {
        "typeWebhook": "incomingMessageReceived",
        "instanceData": {
            "idInstance": 1234567,
            "wid": "972555000000@c.us",
            "typeInstance": "whatsapp",
        },
        "timestamp": 1700000005,
        "idMessage": id_message,
        "senderData": {
            "chatId": "972501234567@c.us",
            "sender": "972501234567@c.us",
            "senderName": "Test User",
        },
        "messageData": {
            "typeMessage": "imageMessage",
            "imageMessageData": {
                "urlFile": "https://example.com/image.jpg",
                "caption": caption,
            },
        },
    }


def state_change(id_message: str = "msg-state-001") -> dict:
    """Instance state change event (e.g. connected/disconnected) — should be filtered."""
    return {
        "typeWebhook": "stateInstanceChanged",
        "instanceData": {
            "idInstance": 1234567,
            "wid": "972555000000@c.us",
            "typeInstance": "whatsapp",
        },
        "timestamp": 1700000006,
        "idMessage": id_message,
        "stateInstance": "authorized",
    }
