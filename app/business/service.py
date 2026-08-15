"""Business domain service.

All methods are tenant-scoped by ``business_id`` supplied from the authenticated
principal; the service never trusts a business id taken from a request body/path
for a different tenant.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.business.models import Business, PaymentPreference
from app.business.repository import BusinessRepository
from app.business.schemas import BusinessUpdate
from app.common.exceptions import ConflictError, NotFoundError, ValidationError
from app.common.security import hash_secret, verify_secret


class BusinessService:
    def __init__(self, session: Session, businesses: BusinessRepository) -> None:
        self._session = session
        self._businesses = businesses

    def _require(self, business_id: int) -> Business:
        business = self._businesses.get(business_id)
        if business is None:
            raise NotFoundError("business not found")
        return business

    def get(self, business_id: int) -> Business:
        return self._require(business_id)

    def update_profile(self, business_id: int, payload: BusinessUpdate) -> Business:
        business = self._require(business_id)
        data = payload.model_dump(exclude_unset=True)
        try:
            for field, value in data.items():
                setattr(business, field, value)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(business)
        return business

    def link_whatsapp(self, business_id: int, whatsapp_number: str) -> Business:
        business = self._require(business_id)
        # Reject if the number is already linked to a different business (UC-01).
        existing = self._businesses.whatsapp_number_exists(whatsapp_number)
        if existing and business.whatsapp_number != whatsapp_number:
            raise ConflictError("whatsapp number is already linked to another business")
        try:
            business.whatsapp_number = whatsapp_number
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(business)
        return business

    def link_whatsapp_phone_number_id(self, business_id: int, phone_number_id: str) -> Business:
        """Map a Meta WhatsApp ``phone_number_id`` to this business.

        Trusted server-side configuration used by the inbound webhook to resolve
        the tenant. Rejects a value already linked to a different business.
        """
        business = self._require(business_id)
        existing = self._businesses.phone_number_id_exists(phone_number_id)
        if existing and business.whatsapp_phone_number_id != phone_number_id:
            raise ConflictError("whatsapp phone_number_id is already linked to another business")
        try:
            business.whatsapp_phone_number_id = phone_number_id
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(business)
        return business

    def update_payment_preference(
        self, business_id: int, preference: PaymentPreference
    ) -> Business:
        business = self._require(business_id)
        try:
            business.payment_preference = preference
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(business)
        return business

    def set_pin(self, business_id: int, pin: str) -> None:
        business = self._require(business_id)
        try:
            business.pin_hash = hash_secret(pin)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def verify_pin(self, business_id: int, pin: str) -> bool:
        business = self._require(business_id)
        if business.pin_hash is None:
            raise ValidationError("business PIN is not set")
        return verify_secret(pin, business.pin_hash)
