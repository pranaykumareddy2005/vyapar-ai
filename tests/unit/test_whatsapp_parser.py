"""Unit tests for the Meta webhook parser (normalization boundary)."""

from __future__ import annotations

from typing import Any

from app.common.messaging import MessageType
from app.whatsapp.parser import MetaWhatsAppParser

_PNID = "1324744104046168"


def _envelope(*messages: dict[str, Any], contacts: list[dict[str, Any]] | None = None) -> dict:
    value: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15550000000", "phone_number_id": _PNID},
        "messages": list(messages),
    }
    if contacts is not None:
        value["contacts"] = contacts
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA", "changes": [{"value": value, "field": "messages"}]}],
    }


def _text_message(body: str, *, mid: str = "wamid.1") -> dict[str, Any]:
    return {
        "from": "919111111111",
        "id": mid,
        "timestamp": "1699999999",
        "type": "text",
        "text": {"body": body},
    }


def test_parses_text_message() -> None:
    payload = _envelope(
        _text_message("How many notebooks?"),
        contacts=[{"profile": {"name": "Asha"}, "wa_id": "919111111111"}],
    )
    [msg] = MetaWhatsAppParser.parse(payload)
    assert msg.message_type is MessageType.TEXT
    assert msg.text == "How many notebooks?"
    assert msg.sender_phone == "919111111111"
    assert msg.message_id == "wamid.1"
    assert msg.phone_number_id == _PNID
    assert msg.profile_name == "Asha"
    assert msg.timestamp is not None


def test_parses_multilingual_text_verbatim() -> None:
    payload = _envelope(_text_message("నోట్‌బుక్స్ ఎన్ని ఉన్నాయి?"))
    [msg] = MetaWhatsAppParser.parse(payload)
    assert msg.text == "నోట్‌బుక్స్ ఎన్ని ఉన్నాయి?"
    assert msg.message_type is MessageType.TEXT


def test_parses_image_message_with_caption() -> None:
    image_msg = {
        "from": "919111111111",
        "id": "wamid.img",
        "timestamp": "1699999999",
        "type": "image",
        "image": {"id": "MEDIA123", "mime_type": "image/jpeg", "caption": "my product"},
    }
    [msg] = MetaWhatsAppParser.parse(_envelope(image_msg))
    assert msg.message_type is MessageType.IMAGE
    assert msg.media is not None
    assert msg.media.media_id == "MEDIA123"
    assert msg.media.mime_type == "image/jpeg"
    assert msg.text == "my product"


def test_image_without_media_id_is_unsupported() -> None:
    bad = {"from": "919111111111", "id": "wamid.badimg", "type": "image", "image": {}}
    [msg] = MetaWhatsAppParser.parse(_envelope(bad))
    assert msg.message_type is MessageType.UNSUPPORTED


def test_other_types_are_unsupported() -> None:
    audio = {"from": "919111111111", "id": "wamid.audio", "type": "audio", "audio": {"id": "A1"}}
    [msg] = MetaWhatsAppParser.parse(_envelope(audio))
    assert msg.message_type is MessageType.UNSUPPORTED
    assert msg.raw_type == "audio"


def test_status_callback_yields_nothing() -> None:
    status_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": _PNID},
                            "statuses": [{"id": "wamid.x", "status": "delivered"}],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    assert MetaWhatsAppParser.parse(status_payload) == []


def test_multiple_messages_all_parsed() -> None:
    payload = _envelope(
        _text_message("first", mid="wamid.a"), _text_message("second", mid="wamid.b")
    )
    msgs = MetaWhatsAppParser.parse(payload)
    assert [m.message_id for m in msgs] == ["wamid.a", "wamid.b"]


def test_message_without_id_skipped() -> None:
    no_id = {"from": "919111111111", "type": "text", "text": {"body": "hi"}}
    assert MetaWhatsAppParser.parse(_envelope(no_id)) == []


def test_missing_phone_number_id_skipped() -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "value": {
                            "metadata": {},
                            "messages": [_text_message("hi")],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    assert MetaWhatsAppParser.parse(payload) == []


def test_malformed_payloads_never_raise() -> None:
    assert MetaWhatsAppParser.parse({}) == []
    assert MetaWhatsAppParser.parse({"entry": "not-a-list"}) == []
    assert MetaWhatsAppParser.parse({"entry": [{"changes": [{"value": None}]}]}) == []
    assert MetaWhatsAppParser.parse({"entry": [{}]}) == []


def test_parses_button_reply() -> None:
    msg = {
        "from": "919111111111",
        "id": "wamid.btn",
        "type": "interactive",
        "interactive": {
            "type": "button_reply",
            "button_reply": {"id": "menu:browse", "title": "🛍️ Browse"},
        },
    }
    [parsed] = MetaWhatsAppParser.parse(_envelope(msg))
    assert parsed.message_type is MessageType.INTERACTIVE
    assert parsed.interactive_id == "menu:browse"
    assert parsed.interactive_title == "🛍️ Browse"


def test_parses_list_reply() -> None:
    msg = {
        "from": "919111111111",
        "id": "wamid.list",
        "type": "interactive",
        "interactive": {
            "type": "list_reply",
            "list_reply": {"id": "prod:42", "title": "Notebook", "description": "₹50"},
        },
    }
    [parsed] = MetaWhatsAppParser.parse(_envelope(msg))
    assert parsed.message_type is MessageType.INTERACTIVE
    assert parsed.interactive_id == "prod:42"


def test_parses_template_button_quick_reply() -> None:
    msg = {
        "from": "919111111111",
        "id": "wamid.tbtn",
        "type": "button",
        "button": {"payload": "confirm:yes", "text": "Yes"},
    }
    [parsed] = MetaWhatsAppParser.parse(_envelope(msg))
    assert parsed.message_type is MessageType.INTERACTIVE
    assert parsed.interactive_id == "confirm:yes"


def test_interactive_without_id_is_unsupported() -> None:
    msg = {
        "from": "919111111111",
        "id": "wamid.badint",
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"title": "no id"}},
    }
    [parsed] = MetaWhatsAppParser.parse(_envelope(msg))
    assert parsed.message_type is MessageType.UNSUPPORTED
