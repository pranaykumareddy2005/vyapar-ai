"""FastAPI wiring for the invoice service."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.business.repository import BusinessRepository
from app.common.storage import ObjectStorage
from app.config import Settings, get_settings
from app.customer.repository import CustomerRepository
from app.db import get_session
from app.invoice.repository import (
    InvoiceCounterRepository,
    InvoiceItemRepository,
    InvoiceRepository,
)
from app.invoice.service import InvoiceService
from app.order.repository import OrderRepository
from app.payment.repository import PaymentRepository
from app.providers import get_object_storage


def get_invoice_service(
    session: Session = Depends(get_session),
    storage: ObjectStorage = Depends(get_object_storage),
    settings: Settings = Depends(get_settings),
) -> InvoiceService:
    return InvoiceService(
        session,
        InvoiceRepository(session),
        InvoiceItemRepository(session),
        InvoiceCounterRepository(session),
        OrderRepository(session),
        CustomerRepository(session),
        BusinessRepository(session),
        PaymentRepository(session),
        storage,
        default_currency=settings.default_currency,
    )
