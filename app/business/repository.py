"""Data access for businesses. All merchant-scoped access goes by id."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.business.models import Business


class BusinessRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, business: Business) -> Business:
        self._session.add(business)
        self._session.flush()
        return business

    def get(self, business_id: int) -> Business | None:
        return self._session.get(Business, business_id)

    def whatsapp_number_exists(self, whatsapp_number: str) -> bool:
        stmt = select(Business.id).where(Business.whatsapp_number == whatsapp_number)
        return self._session.scalars(stmt).first() is not None

    def get_by_phone_number_id(self, phone_number_id: str) -> Business | None:
        """Resolve the tenant for an inbound WhatsApp message.

        The Meta ``phone_number_id`` is trusted server-side configuration (set by
        the merchant when connecting WhatsApp), never taken from message content.
        """
        stmt = select(Business).where(
            Business.whatsapp_phone_number_id == phone_number_id,
            Business.is_active.is_(True),
        )
        return self._session.scalars(stmt).one_or_none()

    def phone_number_id_exists(self, phone_number_id: str) -> bool:
        stmt = select(Business.id).where(Business.whatsapp_phone_number_id == phone_number_id)
        return self._session.scalars(stmt).first() is not None
