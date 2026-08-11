"""Messaging provider abstraction and the normalized message model.

WhatsApp is an *external interface*, not the core business layer. The
conversation/business engine operates only on the vendor-neutral
:class:`IncomingMessage` / :class:`OutgoingMessage` models defined here and
talks to the :class:`MessagingProvider` protocol.

Concrete providers:
  - :class:`MockMessagingProvider` (this module) - dev/testing, no network.
  - ``WhatsAppMessagingProvider`` - added in Phase 5, translates Meta payloads
    to/from these models and calls the Meta Cloud API.

No Meta-specific payload structure may leak past a provider implementation.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


class MessageType(enum.StrEnum):
    TEXT = "text"
    IMAGE = "image"
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
        self._counter = 0

    def send(self, message: OutgoingMessage) -> SendResult:
        self._counter += 1
        self.sent.append(message)
        return SendResult(provider_message_id=f"mock-{self._counter}", accepted=True)

    def last_to(self, phone: str) -> OutgoingMessage | None:
        """Return the most recent message sent to ``phone`` (test helper)."""
        for msg in reversed(self.sent):
            if msg.recipient_phone == phone:
                return msg
        return None

    def clear(self) -> None:
        self.sent.clear()
        self._counter = 0
