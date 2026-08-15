"""The rich outbound surface the WhatsApp UX layer needs.

The generic :class:`~app.common.messaging.MessagingProvider` only guarantees
``send`` (text/template). The interactive UX (buttons, list menus, media, read
receipts) needs more, so the router depends on this ``WhatsAppChannel`` protocol
instead. Both :class:`~app.whatsapp.provider.MetaWhatsAppProvider` (production)
and :class:`~app.common.messaging.MockMessagingProvider` (tests) satisfy it, so
the channel is swappable and fully testable without the network.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.common.messaging import OutgoingMessage, SendResult


@runtime_checkable
class WhatsAppChannel(Protocol):
    def send(self, message: OutgoingMessage) -> SendResult: ...

    def send_buttons(
        self,
        recipient_phone: str,
        *,
        body: str,
        buttons: list[tuple[str, str]],
        header: str | None = None,
    ) -> SendResult: ...

    def send_list(
        self,
        recipient_phone: str,
        *,
        body: str,
        button_text: str,
        rows: list[tuple[str, str, str | None]],
        header: str | None = None,
        section_title: str = "Options",
    ) -> SendResult: ...

    def send_image(
        self, recipient_phone: str, *, media_id: str, caption: str | None = None
    ) -> SendResult: ...

    def send_document(
        self, recipient_phone: str, *, media_id: str, filename: str, caption: str | None = None
    ) -> SendResult: ...

    def upload_media(self, data: bytes, *, filename: str, mime_type: str) -> str: ...

    def download_media(self, media_id: str) -> tuple[bytes, str]: ...

    def mark_read(self, message_id: str) -> bool: ...
