"""Persistence for webhook idempotency.

``try_claim`` is the atomic gate: it inserts the provider message id inside a
SAVEPOINT so a unique-violation (a duplicate delivery, possibly concurrent) rolls
back only the nested insert and leaves the outer transaction usable, returning
``False``. The first caller to claim an id wins; everyone else is told it is a
duplicate.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.whatsapp.models import ProcessedWebhookEvent, WhatsAppSession, WhatsAppStaff


class WebhookEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def try_claim(
        self,
        provider_message_id: str,
        *,
        business_id: int | None = None,
        event_type: str | None = None,
    ) -> bool:
        """Record the event id; return ``True`` if newly claimed, ``False`` if a
        duplicate (already recorded)."""
        try:
            with self._session.begin_nested():
                self._session.add(
                    ProcessedWebhookEvent(
                        provider_message_id=provider_message_id,
                        business_id=business_id,
                        event_type=event_type,
                    )
                )
            return True
        except IntegrityError:
            # Another delivery already claimed this id; the SAVEPOINT rollback
            # keeps the surrounding transaction intact.
            return False


class WhatsAppSessionRepository:
    """Persistence for per-(business, phone) conversation state."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, business_id: int, phone: str) -> WhatsAppSession | None:
        stmt = select(WhatsAppSession).where(
            WhatsAppSession.business_id == business_id, WhatsAppSession.phone == phone
        )
        return self._session.scalars(stmt).one_or_none()

    def get_or_create(self, business_id: int, phone: str) -> WhatsAppSession:
        existing = self.get(business_id, phone)
        if existing is not None:
            return existing
        session = WhatsAppSession(business_id=business_id, phone=phone, state="MENU", data=None)
        self._session.add(session)
        self._session.flush()
        return session


class WhatsAppStaffRepository:
    """Trusted seller/staff lookup by phone within a business."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def is_staff(self, business_id: int, phone: str) -> bool:
        stmt = select(WhatsAppStaff.id).where(
            WhatsAppStaff.business_id == business_id, WhatsAppStaff.phone == phone
        )
        return self._session.scalars(stmt).first() is not None

    def get_staff(self, business_id: int, phone: str) -> WhatsAppStaff | None:
        stmt = select(WhatsAppStaff).where(
            WhatsAppStaff.business_id == business_id, WhatsAppStaff.phone == phone
        )
        return self._session.scalars(stmt).one_or_none()
