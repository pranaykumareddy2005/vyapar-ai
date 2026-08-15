"""Inbound normalization boundary: Meta webhook JSON -> neutral message.

Raw Meta payloads never travel past this module. The parser is defensive: any
missing/malformed field yields *fewer* parsed messages (or none), never an
exception that reaches the request handler - a bad payload must be a controlled
200/ignore, not a crash.

The parser deliberately does NOT know about businesses. It surfaces the Meta
``phone_number_id`` (the destination line's asset id) so the webhook service can
resolve the tenant from trusted server-side mapping; ``business_id`` is never
derived from message content.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.common.messaging import MediaRef, MessageType


@dataclass(frozen=True, slots=True)
class ParsedWhatsAppMessage:
    """A single inbound WhatsApp message, normalized but not yet tenant-scoped."""

    phone_number_id: str
    sender_phone: str
    message_id: str
    message_type: MessageType
    text: str | None = None
    media: MediaRef | None = None
    # For a tapped reply button / list row: the deterministic id WE assigned when
    # building the interactive message (trusted; never free-form user input). The
    # router maps this id to a domain action. ``interactive_title`` is the visible
    # label, kept only for logging/echo.
    interactive_id: str | None = None
    interactive_title: str | None = None
    timestamp: datetime | None = None
    profile_name: str | None = None
    # Original Meta ``type`` string (e.g. "audio", "document") for logging only.
    raw_type: str = ""


def _coerce_timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _parse_one(
    message: dict[str, Any], phone_number_id: str, profile_name: str | None
) -> ParsedWhatsAppMessage | None:
    sender = message.get("from")
    message_id = message.get("id")
    if not sender or not message_id:
        return None  # unusable without a sender + id (id is the dedup key)

    raw_type = str(message.get("type") or "")
    timestamp = _coerce_timestamp(message.get("timestamp"))

    def _build(
        message_type: MessageType,
        *,
        text: str | None = None,
        media: MediaRef | None = None,
        interactive_id: str | None = None,
        interactive_title: str | None = None,
    ) -> ParsedWhatsAppMessage:
        return ParsedWhatsAppMessage(
            phone_number_id=phone_number_id,
            sender_phone=str(sender),
            message_id=str(message_id),
            message_type=message_type,
            text=text,
            media=media,
            interactive_id=interactive_id,
            interactive_title=interactive_title,
            timestamp=timestamp,
            profile_name=profile_name,
            raw_type=raw_type,
        )

    if raw_type == "text":
        body = (message.get("text") or {}).get("body")
        text = str(body).strip() if body is not None else None
        return _build(MessageType.TEXT, text=text or None)

    if raw_type == "interactive":
        # A tapped reply button or selected list row.
        interactive = message.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        reply_id = reply.get("id")
        title = reply.get("title")
        if not reply_id:
            return _build(MessageType.UNSUPPORTED)
        return _build(
            MessageType.INTERACTIVE,
            interactive_id=str(reply_id),
            interactive_title=str(title) if title else None,
            text=str(title) if title else None,
        )

    if raw_type == "button":
        # Quick-reply from a template button. Carries a payload + text.
        button = message.get("button") or {}
        payload = button.get("payload") or button.get("text")
        if not payload:
            return _build(MessageType.UNSUPPORTED)
        return _build(
            MessageType.INTERACTIVE,
            interactive_id=str(payload),
            interactive_title=str(button.get("text")) if button.get("text") else None,
            text=str(button.get("text")) if button.get("text") else None,
        )

    if raw_type == "image":
        image = message.get("image") or {}
        media_id = image.get("id")
        if not media_id:
            return _build(MessageType.UNSUPPORTED)
        caption = image.get("caption")
        return _build(
            MessageType.IMAGE,
            text=str(caption).strip() if caption else None,
            media=MediaRef(
                media_id=str(media_id),
                mime_type=str(image.get("mime_type") or "image/jpeg"),
            ),
        )

    # Any other Meta type (audio, video, document, location, interactive, ...)
    # is normalized to UNSUPPORTED so the pipeline can reply gracefully.
    return _build(MessageType.UNSUPPORTED)


class MetaWhatsAppParser:
    """Translate a Meta webhook body into normalized inbound messages."""

    @staticmethod
    def parse(payload: dict[str, Any]) -> list[ParsedWhatsAppMessage]:
        """Return every inbound *message* in the payload (status callbacks and
        malformed entries are skipped). Never raises on shape issues."""
        if not isinstance(payload, dict):
            return []
        results: list[ParsedWhatsAppMessage] = []
        for entry in _as_list(payload.get("entry")):
            for change in _as_list(_get(entry, "changes")):
                value = _get(change, "value")
                if not isinstance(value, dict):
                    continue
                metadata = value.get("metadata") or {}
                phone_number_id = metadata.get("phone_number_id")
                if not phone_number_id:
                    continue  # cannot resolve a tenant without the destination id
                messages = value.get("messages")
                if not isinstance(messages, list):
                    continue  # e.g. a "statuses" delivery receipt -> nothing to do
                profile_name = _first_profile_name(value.get("contacts"))
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    parsed = _parse_one(message, str(phone_number_id), profile_name)
                    if parsed is not None:
                        results.append(parsed)
        return results


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _get(container: Any, key: str) -> Any:
    return container.get(key) if isinstance(container, dict) else None


def _first_profile_name(contacts: Any) -> str | None:
    for contact in _as_list(contacts):
        if isinstance(contact, dict):
            name = (contact.get("profile") or {}).get("name")
            if name:
                return str(name)
    return None
