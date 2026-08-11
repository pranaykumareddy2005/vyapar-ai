"""Pydantic schemas for the business domain.

No schema ever exposes ``pin_hash``. ``BusinessOut`` reports only whether a PIN
has been set via the derived ``pin_set`` flag.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.business.models import Business, PaymentPreference


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    contact_number: str
    address: str
    whatsapp_number: str | None
    payment_preference: PaymentPreference
    is_active: bool
    pin_set: bool

    @classmethod
    def from_model(cls, business: Business) -> BusinessOut:
        return cls(
            id=business.id,
            name=business.name,
            category=business.category,
            contact_number=business.contact_number,
            address=business.address,
            whatsapp_number=business.whatsapp_number,
            payment_preference=business.payment_preference,
            is_active=business.is_active,
            pin_set=business.pin_hash is not None,
        )


class BusinessUpdate(BaseModel):
    """Partial profile edit (FR-BUS-03). Only provided fields change."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    contact_number: str | None = Field(default=None, min_length=3, max_length=20)
    address: str | None = Field(default=None, min_length=1, max_length=500)


class WhatsappLinkRequest(BaseModel):
    whatsapp_number: str = Field(min_length=3, max_length=20)


class PaymentPreferenceUpdate(BaseModel):
    payment_preference: PaymentPreference


class PinSetRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=12, pattern=r"^\d+$")
