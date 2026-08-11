"""Pydantic schemas for the invoice API edge.

The client supplies only which order to invoice. It never supplies invoice number,
amounts, tax, payment status, or any snapshot value - all are server-derived from
authoritative Order/Payment data.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.invoice.models import Invoice, InvoiceItem


class InvoiceCreate(BaseModel):
    order_id: int


class InvoiceItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_name: str
    unit_price: Decimal
    quantity: int
    line_total: Decimal


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    order_id: int
    invoice_number: str
    status: str
    currency: str
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    customer_name: str
    customer_phone: str
    business_name: str
    payment_method: str | None
    payment_status: str
    pdf_available: bool
    items: list[InvoiceItemOut]

    @classmethod
    def from_model(cls, invoice: Invoice) -> InvoiceOut:
        items: list[InvoiceItem] = list(invoice.items)
        return cls(
            id=invoice.id,
            business_id=invoice.business_id,
            order_id=invoice.order_id,
            invoice_number=invoice.invoice_number,
            status=invoice.status.value,
            currency=invoice.currency,
            subtotal=invoice.subtotal_amt,
            tax=invoice.tax_amt,
            total=invoice.total_amt,
            customer_name=invoice.customer_name,
            customer_phone=invoice.customer_phone,
            business_name=invoice.business_name,
            payment_method=invoice.payment_method,
            payment_status=invoice.payment_status,
            pdf_available=invoice.pdf_storage_key is not None,
            items=[InvoiceItemOut.model_validate(i) for i in items],
        )
