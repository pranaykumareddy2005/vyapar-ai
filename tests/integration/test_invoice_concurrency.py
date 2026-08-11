"""Concurrency tests: duplicate invoice generation & numbering race (§30).

Real PostgreSQL, separate connections/threads. The unique ``order_id`` constraint
guarantees one invoice per order; the atomic counter UPSERT (row-locked until
commit) guarantees gap-free, non-duplicate sequential numbers. SQLite is not used.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from app.auth.models import User
from app.business.models import Business
from app.business.repository import BusinessRepository
from app.catalog.models import Product
from app.common.exceptions import ConflictError
from app.common.security import Role
from app.common.storage import InMemoryStorage
from app.customer.models import Customer
from app.customer.repository import CustomerRepository
from app.db import SessionLocal
from app.invoice.models import Invoice
from app.invoice.repository import (
    InvoiceCounterRepository,
    InvoiceItemRepository,
    InvoiceRepository,
)
from app.invoice.service import InvoiceService
from app.order.models import Order, OrderItem, OrderStatus
from app.order.repository import OrderRepository
from app.payment.models import Payment, PaymentMethod, PaymentStatus
from app.payment.repository import PaymentRepository
from sqlalchemy import delete, func, select


def _invoice_service(session: object) -> InvoiceService:
    return InvoiceService(
        session,  # type: ignore[arg-type]
        InvoiceRepository(session),  # type: ignore[arg-type]
        InvoiceItemRepository(session),  # type: ignore[arg-type]
        InvoiceCounterRepository(session),  # type: ignore[arg-type]
        OrderRepository(session),  # type: ignore[arg-type]
        CustomerRepository(session),  # type: ignore[arg-type]
        BusinessRepository(session),  # type: ignore[arg-type]
        PaymentRepository(session),  # type: ignore[arg-type]
        InMemoryStorage(),
        default_currency="INR",
    )


@contextmanager
def _paid_orders(n: int) -> Iterator[tuple[int, list[int]]]:
    session = SessionLocal()
    try:
        biz = Business(
            name="InvConc", category="grocery", contact_number="+910000000000", address="a"
        )
        session.add(biz)
        session.flush()
        session.add(
            User(business_id=biz.id, email=f"ic-{biz.id}@x.co", password_hash="x", role=Role.OWNER)
        )
        product = Product(
            business_id=biz.id, name="P", price_amt=Decimal("40.00"), sku=f"IC-{biz.id}"
        )
        session.add(product)
        customer = Customer(business_id=biz.id, name="C", phone=f"+9100{biz.id}")
        session.add(customer)
        session.flush()
        order_ids = []
        for _ in range(n):
            order = Order(
                business_id=biz.id,
                customer_id=customer.id,
                status=OrderStatus.PAID,
                tax_amt=Decimal("0.00"),
                total_amt=Decimal("40.00"),
            )
            session.add(order)
            session.flush()
            session.add(
                OrderItem(
                    business_id=biz.id,
                    order_id=order.id,
                    product_id=product.id,
                    product_name="P",
                    unit_price=Decimal("40.00"),
                    quantity=1,
                )
            )
            session.add(
                Payment(
                    business_id=biz.id,
                    order_id=order.id,
                    method=PaymentMethod.ONLINE,
                    amount=Decimal("40.00"),
                    currency="INR",
                    status=PaymentStatus.SUCCESS,
                    provider="mock",
                    provider_payment_id=f"pay_{order.id}",
                )
            )
            order_ids.append(order.id)
        session.commit()
        ids = (biz.id, order_ids)
    finally:
        session.close()
    try:
        yield ids
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.execute(delete(Invoice).where(Invoice.business_id == ids[0]))
            cleanup.execute(delete(Payment).where(Payment.business_id == ids[0]))
            cleanup.execute(delete(Order).where(Order.business_id == ids[0]))
            cleanup.execute(delete(Business).where(Business.id == ids[0]))
            cleanup.commit()
        finally:
            cleanup.close()


def _run(business_id: int, order_ids: list[int]) -> list[str]:
    results: list[str] = ["" for _ in order_ids]
    barrier = threading.Barrier(len(order_ids))

    def worker(index: int, order_id: int) -> None:
        session = SessionLocal()
        try:
            service = _invoice_service(session)
            barrier.wait()
            invoice = service.generate(business_id, order_id)
            results[index] = f"ok:{invoice.invoice_number}"
        except ConflictError:
            results[index] = "conflict"
        except Exception as exc:  # pragma: no cover
            results[index] = f"error:{exc}"
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(i, oid)) for i, oid in enumerate(order_ids)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def _invoice_count(business_id: int) -> int:
    session = SessionLocal()
    try:
        return session.execute(
            select(func.count()).select_from(Invoice).where(Invoice.business_id == business_id)
        ).scalar_one()
    finally:
        session.close()


def test_concurrent_generation_same_order_one_invoice() -> None:
    with _paid_orders(1) as (biz_id, order_ids):
        results = _run(biz_id, [order_ids[0], order_ids[0]])
        oks = [r for r in results if r.startswith("ok:")]
        # Both requests resolve to the same single invoice number (idempotent).
        assert len(oks) == 2
        assert oks[0] == oks[1]
        assert _invoice_count(biz_id) == 1


def test_concurrent_numbering_is_unique_and_sequential() -> None:
    with _paid_orders(2) as (biz_id, order_ids):
        results = _run(biz_id, order_ids)
        numbers = sorted(r.split(":", 1)[1] for r in results if r.startswith("ok:"))
        assert len(numbers) == 2
        assert len(set(numbers)) == 2  # no duplicate numbers
        assert numbers[0].endswith("-0001")
        assert numbers[1].endswith("-0002")
        assert _invoice_count(biz_id) == 2
