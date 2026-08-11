"""Invoice application service - owns invoice business rules.

Generates an immutable invoice snapshot from a PAID order (financial totals from
the Order, line items from the OrderItem snapshots, customer/business/payment info
read from authoritative rows). It never modifies orders, inventory, or payment
state. Numbering is gap-free per business per year; one invoice per order is
enforced by the DB. The PDF is rendered from the snapshot after the invoice is
committed, so a slow render never holds the invoice transaction.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.business.repository import BusinessRepository
from app.common.exceptions import ConflictError, NotFoundError
from app.common.storage import ObjectStorage
from app.customer.repository import CustomerRepository
from app.invoice.models import Invoice, InvoiceItem, InvoiceStatus
from app.invoice.pdf import render_invoice_pdf
from app.invoice.repository import (
    InvoiceCounterRepository,
    InvoiceItemRepository,
    InvoiceRepository,
)
from app.order.models import Order, OrderStatus
from app.order.repository import OrderRepository
from app.payment.repository import PaymentRepository

logger = logging.getLogger(__name__)

# An invoice may be issued only once the order is paid (or a later fulfillment
# state), i.e. a successful payment exists (docs/phase9_schema_decision.md D1).
INVOICEABLE_STATES: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.PAID,
        OrderStatus.PACKED,
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
        OrderStatus.COMPLETED,
    }
)

_PDF_CONTENT_TYPE = "application/pdf"


class InvoiceService:
    def __init__(
        self,
        session: Session,
        invoices: InvoiceRepository,
        invoice_items: InvoiceItemRepository,
        counters: InvoiceCounterRepository,
        orders: OrderRepository,
        customers: CustomerRepository,
        businesses: BusinessRepository,
        payments: PaymentRepository,
        storage: ObjectStorage,
        *,
        default_currency: str,
    ) -> None:
        self._session = session
        self._invoices = invoices
        self._invoice_items = invoice_items
        self._counters = counters
        self._orders = orders
        self._customers = customers
        self._businesses = businesses
        self._payments = payments
        self._storage = storage
        self._default_currency = default_currency

    # --- queries ----------------------------------------------------------

    def get(self, business_id: int, invoice_id: int) -> Invoice:
        invoice = self._invoices.get(business_id, invoice_id)
        if invoice is None:
            raise NotFoundError("invoice not found")
        return invoice

    def list_invoices(self, business_id: int) -> list[Invoice]:
        return self._invoices.list(business_id)

    # --- generation -------------------------------------------------------

    def generate(self, business_id: int, order_id: int) -> Invoice:
        """Create the (single) immutable invoice for a paid order, then render its
        PDF. Idempotent: a repeat request returns the existing invoice."""
        order = self._orders.get(business_id, order_id)
        if order is None:
            raise NotFoundError("order not found")
        if order.status not in INVOICEABLE_STATES:
            raise ConflictError("order must be paid before an invoice can be issued")

        existing = self._invoices.get_by_order(business_id, order_id)
        if existing is not None:
            return existing

        invoice = self._create_snapshot(business_id, order)
        self._ensure_pdf(invoice)
        return invoice

    def _create_snapshot(self, business_id: int, order: Order) -> Invoice:
        customer = self._customers.get(business_id, order.customer_id, include_deleted=True)
        business = self._businesses.get(business_id)
        payment = self._payments.get_successful_for_order(business_id, order.id)
        currency = payment.currency if payment is not None else self._default_currency
        subtotal = order.total_amt - order.tax_amt
        now = datetime.now(UTC)

        try:
            seq = self._counters.next_sequence(business_id, now.year)
            invoice = self._invoices.add(
                Invoice(
                    business_id=business_id,
                    order_id=order.id,
                    invoice_number=f"INV-{now.year}-{seq:04d}",
                    status=InvoiceStatus.ISSUED,
                    issued_at=now,
                    currency=currency,
                    subtotal_amt=subtotal,
                    tax_amt=order.tax_amt,
                    total_amt=order.total_amt,
                    customer_name=customer.name if customer is not None else "",
                    customer_phone=customer.phone if customer is not None else "",
                    business_name=business.name if business is not None else "",
                    payment_method=payment.method.value if payment is not None else None,
                    payment_reference=payment.provider_payment_id if payment is not None else None,
                    payment_status="PAID",
                )
            )
            for item in order.items:
                self._invoice_items.add(
                    InvoiceItem(
                        business_id=business_id,
                        invoice_id=invoice.id,
                        product_id=item.product_id,
                        product_name=item.product_name,
                        unit_price=item.unit_price,
                        quantity=item.quantity,
                        line_total=item.line_total(),
                    )
                )
            self._session.commit()
        except IntegrityError as exc:
            # Concurrent duplicate generation for the same order: the unique
            # order_id constraint is the backstop; return the winner idempotently.
            self._session.rollback()
            existing = self._invoices.get_by_order(business_id, order.id)
            if existing is not None:
                return existing
            raise ConflictError("invoice already exists for this order") from exc
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(invoice)
        return invoice

    # --- PDF --------------------------------------------------------------

    def _ensure_pdf(self, invoice: Invoice) -> None:
        """Render + store the PDF from the snapshot (separate transaction).

        On failure the invoice remains ISSUED with no PDF reference (recoverable);
        no fake reference is written.
        """
        try:
            pdf_bytes = render_invoice_pdf(invoice)
            key = f"invoices/{invoice.business_id}/{invoice.id}/invoice.pdf"
            url = self._storage.put(key, pdf_bytes, _PDF_CONTENT_TYPE)
            invoice.pdf_storage_key = key
            invoice.pdf_url = url
            self._session.commit()
        except Exception:
            self._session.rollback()
            logger.exception("invoice PDF generation failed for invoice_id=%s", invoice.id)

    def get_pdf(self, business_id: int, invoice_id: int) -> bytes:
        """Return the invoice PDF bytes, regenerating deterministically from the
        immutable snapshot if the stored document is missing."""
        invoice = self.get(business_id, invoice_id)
        if invoice.pdf_storage_key is not None:
            try:
                return self._storage.get(invoice.pdf_storage_key)
            except Exception:
                logger.warning("stored invoice PDF missing; regenerating invoice_id=%s", invoice.id)

        pdf_bytes = render_invoice_pdf(invoice)
        key = f"invoices/{business_id}/{invoice.id}/invoice.pdf"
        url = self._storage.put(key, pdf_bytes, _PDF_CONTENT_TYPE)
        try:
            invoice.pdf_storage_key = key
            invoice.pdf_url = url
            self._session.commit()
        except Exception:
            self._session.rollback()
        return pdf_bytes
