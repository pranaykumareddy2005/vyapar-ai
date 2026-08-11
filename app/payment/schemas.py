"""Pydantic schemas for the payment API edge.

The client supplies only which order to pay and (for online) the provider payment
id to verify. The client NEVER supplies the amount, currency, business, provider
result, or final status - those are server/provider-authoritative.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from app.payment.models import PaymentMethod

if TYPE_CHECKING:
    from app.payment.models import Payment


class PaymentInitiate(BaseModel):
    order_id: int
    method: PaymentMethod = PaymentMethod.ONLINE


class PaymentVerify(BaseModel):
    provider_payment_id: str = Field(min_length=1, max_length=128)


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    order_id: int
    method: str
    amount: Decimal
    currency: str
    status: str
    provider: str
    provider_order_id: str | None
    provider_payment_id: str | None
    payment_url: str | None = None
    failure_code: str | None

    @classmethod
    def from_model(cls, payment: Payment, *, payment_url: str | None = None) -> PaymentOut:
        return cls(
            id=payment.id,
            business_id=payment.business_id,
            order_id=payment.order_id,
            method=payment.method.value,
            amount=payment.amount,
            currency=payment.currency,
            status=payment.status.value,
            provider=payment.provider,
            provider_order_id=payment.provider_order_id,
            provider_payment_id=payment.provider_payment_id,
            payment_url=payment_url,
            failure_code=payment.failure_code,
        )
