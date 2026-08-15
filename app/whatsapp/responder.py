"""Safe outbound helper bound to one conversation.

Every outbound send goes through here so a Meta API failure (timeout, rate limit,
transient 5xx) is logged and swallowed rather than crashing webhook handling - the
webhook must still return 200 and the rest of the batch must still process. The
provider already retries transient failures; this is the final safety net.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.common.messaging import OutgoingMessage, SendResult
from app.whatsapp.channel import WhatsAppChannel
from app.whatsapp.menus import ButtonMenu, ListMenu
from app.whatsapp.provider import MetaWhatsAppError

logger = logging.getLogger(__name__)


class WhatsAppResponder:
    def __init__(self, channel: WhatsAppChannel, business_id: int, recipient_phone: str) -> None:
        self._channel = channel
        self._business_id = business_id
        self._to = recipient_phone

    def text(self, body: str) -> bool:
        return self._safe(
            lambda: self._channel.send(
                OutgoingMessage(business_id=self._business_id, recipient_phone=self._to, text=body)
            )
        )

    def buttons(self, menu: ButtonMenu) -> bool:
        return self._safe(
            lambda: self._channel.send_buttons(
                self._to, body=menu.body, buttons=menu.buttons, header=menu.header
            )
        )

    def list_menu(self, menu: ListMenu) -> bool:
        return self._safe(
            lambda: self._channel.send_list(
                self._to,
                body=menu.body,
                button_text=menu.button_text,
                rows=menu.rows,
                header=menu.header,
                section_title=menu.section_title,
            )
        )

    def image(self, media_id: str, caption: str | None = None) -> bool:
        return self._safe(
            lambda: self._channel.send_image(self._to, media_id=media_id, caption=caption)
        )

    def document(self, media_id: str, filename: str, caption: str | None = None) -> bool:
        return self._safe(
            lambda: self._channel.send_document(
                self._to, media_id=media_id, filename=filename, caption=caption
            )
        )

    def mark_read(self, message_id: str) -> None:
        try:
            self._channel.mark_read(message_id)
        except MetaWhatsAppError as exc:
            logger.info("whatsapp mark_read failed: %s", exc.code)

    @staticmethod
    def _safe(send: Callable[[], SendResult]) -> bool:
        try:
            send()
            return True
        except MetaWhatsAppError as exc:
            logger.warning("whatsapp outbound send failed: %s", exc.code)
            return False
