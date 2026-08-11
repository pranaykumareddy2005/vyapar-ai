"""FastAPI wiring for the payment service.

Shares one request-scoped ``Session`` with the order service so the payment
SUCCESS write and the order PAID transition commit in a single transaction.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.order.dependencies import get_order_service
from app.order.service import OrderService
from app.payment.provider import PaymentProvider
from app.payment.repository import PaymentRepository
from app.payment.service import PaymentService
from app.providers import get_payment_provider


def get_payment_service(
    session: Session = Depends(get_session),
    orders: OrderService = Depends(get_order_service),
    provider: PaymentProvider = Depends(get_payment_provider),
    settings: Settings = Depends(get_settings),
) -> PaymentService:
    return PaymentService(
        session,
        PaymentRepository(session),
        orders,
        provider,
        currency=settings.default_currency,
    )
