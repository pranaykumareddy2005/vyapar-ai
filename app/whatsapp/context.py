"""Per-message conversation context passed to the flow handlers.

Bundles the server-resolved facts (tenant, sender, role), the persistent session,
the safe responder, and the raw channel (for media up/download). Flow handlers
read/write ``session`` and reply via ``responder``; they never touch Meta wire
formats directly except through ``channel`` media helpers.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.whatsapp.channel import WhatsAppChannel
from app.whatsapp.models import WhatsAppSession
from app.whatsapp.responder import WhatsAppResponder
from app.whatsapp.roles import WhatsAppRole


@dataclass
class Ctx:
    business_id: int
    phone: str
    role: WhatsAppRole
    session: WhatsAppSession
    responder: WhatsAppResponder
    channel: WhatsAppChannel

    def set_state(self, state: str) -> None:
        self.session.state = state

    def put(self, key: str, value: object) -> None:
        data = dict(self.session.data or {})
        data[key] = value
        self.session.data = data

    def get(self, key: str) -> object | None:
        return (self.session.data or {}).get(key)

    def pop(self, key: str) -> None:
        data = dict(self.session.data or {})
        data.pop(key, None)
        self.session.data = data
