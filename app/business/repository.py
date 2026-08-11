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
