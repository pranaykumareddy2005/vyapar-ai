"""Messaging provider abstraction and the normalized message model.

WhatsApp is an *external interface*, not the core business layer. The
conversation/business engine operates only on the vendor-neutral
:class:`IncomingMessage` / :class:`OutgoingMessage` models defined here and
talks to the :class:`MessagingProvider` protocol.

Concrete providers:
  - :class:`MockMessagingProvider` (this module) - dev/testing, no network.

A future ``WhatsAppMessagingProvider`` would translate Meta payloads to/from
these models and call the Meta Cloud API; it is not yet implemented. No
Meta-specific payload structure may leak past a provider implementation.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


class MessageType(enum.StrEnum):
    TEXT = "text"
    IMAGE = "image"
    # A tap on a reply button or a list-menu row (WhatsApp interactive reply).
    INTERACTIVE = "interactive"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class MediaRef:
    """Reference to inbound/outbound media (kept provider-neutral)."""

    media_id: str
    mime_type: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    """Normalized inbound message the conversation engine consumes.

    This is the single representation the engine understands; providers are
    responsible for producing it from their own wire formats.
    """

    business_id: int
    sender_phone: str
    message_id: str
    message_type: MessageType
    text: str | None = None
    media: MediaRef | None = None
    timestamp: datetime | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    """Normalized outbound message the engine asks a provider to send."""

    business_id: int
    recipient_phone: str
    text: str
    # Meta-approved template name for business-initiated messages outside the
    # 24-hour session window. None => free-form reply within the window.
    template_name: str | None = None


@dataclass(frozen=True, slots=True)
class SendResult:
    """Outcome of a send attempt, returned by the provider."""

    provider_message_id: str
    accepted: bool = True


@runtime_checkable
class MessagingProvider(Protocol):
    """Boundary between the engine and any messaging channel."""

    def send(self, message: OutgoingMessage) -> SendResult:
        """Deliver an outbound message; return a provider reference."""
        ...


class MockMessagingProvider:
    """In-memory provider for development and tests.

    Records every outbound message instead of hitting the network, so the
    conversation engine is fully exercisable without WhatsApp credentials.
    """

    def __init__(self) -> None:
        self.sent: list[OutgoingMessage] = []
        # Records for the richer WhatsApp channel surface (buttons/lists/media).
        self.buttons: list[dict[str, object]] = []
        self.lists: list[dict[str, object]] = []
        self.images: list[dict[str, object]] = []
        self.documents: list[dict[str, object]] = []
        self.uploads: list[dict[str, object]] = []
        self.read_receipts: list[str] = []
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"mock-{self._counter}"

    def send(self, message: OutgoingMessage) -> SendResult:
        self.sent.append(message)
        return SendResult(provider_message_id=self._next_id(), accepted=True)

    def send_buttons(
        self,
        recipient_phone: str,
        *,
        body: str,
        buttons: list[tuple[str, str]],
        header: str | None = None,
    ) -> SendResult:
        self.buttons.append({"to": recipient_phone, "body": body, "buttons": buttons})
        return SendResult(provider_message_id=self._next_id(), accepted=True)

    def send_list(
        self,
        recipient_phone: str,
        *,
        body: str,
        button_text: str,
        rows: list[tuple[str, str, str | None]],
        header: str | None = None,
        section_title: str = "Options",
    ) -> SendResult:
        self.lists.append({"to": recipient_phone, "body": body, "rows": rows})
        return SendResult(provider_message_id=self._next_id(), accepted=True)

    def send_image(
        self, recipient_phone: str, *, media_id: str, caption: str | None = None
    ) -> SendResult:
        self.images.append({"to": recipient_phone, "media_id": media_id, "caption": caption})
        return SendResult(provider_message_id=self._next_id(), accepted=True)

    def send_document(
        self, recipient_phone: str, *, media_id: str, filename: str, caption: str | None = None
    ) -> SendResult:
        self.documents.append({"to": recipient_phone, "media_id": media_id, "filename": filename})
        return SendResult(provider_message_id=self._next_id(), accepted=True)

    def upload_media(self, data: bytes, *, filename: str, mime_type: str) -> str:
        self._counter += 1
        media_id = f"mock-media-{self._counter}"
        self.uploads.append({"media_id": media_id, "filename": filename, "bytes": len(data)})
        return media_id

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        # Deterministic fake image so the seller catalogue flow is testable offline.
        return b"\xff\xd8\xff\xe0mock-image-bytes", "image/jpeg"

    def mark_read(self, message_id: str) -> bool:
        self.read_receipts.append(message_id)
        return True

    def last_to(self, phone: str) -> OutgoingMessage | None:
        """Return the most recent message sent to ``phone`` (test helper)."""
        for msg in reversed(self.sent):
            if msg.recipient_phone == phone:
                return msg
        return None

    def clear(self) -> None:
        self.sent.clear()
        self.buttons.clear()
        self.lists.clear()
        self.images.clear()
        self.documents.clear()
        self.uploads.clear()
        self.read_receipts.clear()
        self._counter = 0
