"""Concurrency tests: duplicate verification & competing payments (§26).

Real PostgreSQL, separate connections/threads. A payment row lock plus DB unique
constraints (one SUCCESS per order; one payment per provider payment id) guarantee
no duplicate successful payment, one Order PAID, and no inventory movement from
payment. SQLite is deliberately not used.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from app.auth.models import User
from app.business.models import Business
from app.catalog.models import Product
from app.catalog.repository import ProductRepository
from app.common.events import EventBus
from app.common.security import Role
from app.customer.models import Customer
from app.customer.repository import CustomerRepository
from app.db import SessionLocal
from app.inventory.models import Inventory, StockMovement
from app.inventory.repository import InventoryRepository, StockMovementRepository
from app.inventory.service import InventoryService
from app.order.models import Order, OrderItem, OrderStatus
from app.order.repository import OrderItemRepository, OrderRepository
from app.order.service import OrderService
from app.payment.errors import PaymentStateError
from app.payment.models import Payment, PaymentMethod, PaymentStatus
from app.payment.provider import MockPaymentProvider
from app.payment.repository import PaymentRepository
from app.payment.service import PaymentService
from sqlalchemy import delete, func, select


def _payment_service(session: object) -> PaymentService:
    inventory = InventoryService(
        session,  # type: ignore[arg-type]
        InventoryRepository(session),  # type: ignore[arg-type]
        StockMovementRepository(session),  # type: ignore[arg-type]
        ProductRepository(session),  # type: ignore[arg-type]
        events=EventBus(),
    )
    orders = OrderService(
        session,  # type: ignore[arg-type]
        OrderRepository(session),  # type: ignore[arg-type]
        OrderItemRepository(session),  # type: ignore[arg-type]
        CustomerRepository(session),  # type: ignore[arg-type]
        ProductRepository(session),  # type: ignore[arg-type]
        inventory,
        tax_rate=Decimal("0"),
        events=EventBus(),
    )
    return PaymentService(
        session,  # type: ignore[arg-type]
        PaymentRepository(session),  # type: ignore[arg-type]
        orders,
        MockPaymentProvider(),
        currency="INR",
        events=EventBus(),
    )


@contextmanager
def _confirmed_order_with_payments(n_payments: int) -> Iterator[tuple[int, int, list[int]]]:
    """Committed CONFIRMED order (stock already decremented to 8) with N CREATED
    online payments. Yields (business_id, order_id, [payment_ids]); cleans up."""
    session = SessionLocal()
    try:
        biz = Business(
            name="PayConc", category="grocery", contact_number="+910000000000", address="a"
        )
        session.add(biz)
        session.flush()
        session.add(
            User(business_id=biz.id, email=f"pc-{biz.id}@x.co", password_hash="x", role=Role.OWNER)
        )
        product = Product(
            business_id=biz.id, name="P", price_amt=Decimal("40.00"), sku=f"PC-{biz.id}"
        )
        session.add(product)
        session.flush()
        # Inventory already reflects a confirmed order (no movements needed here;
        # the test asserts payment adds none).
        session.add(
            Inventory(business_id=biz.id, product_id=product.id, quantity=8, low_stock_threshold=0)
        )
        customer = Customer(business_id=biz.id, name="C", phone=f"+9100{biz.id}")
        session.add(customer)
        session.flush()
        order = Order(
            business_id=biz.id,
            customer_id=customer.id,
            status=OrderStatus.CONFIRMED,
            tax_amt=Decimal("0.00"),
            total_amt=Decimal("80.00"),
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
                quantity=2,
            )
        )
        payment_ids = []
        for _ in range(n_payments):
            payment = Payment(
                business_id=biz.id,
                order_id=order.id,
                method=PaymentMethod.ONLINE,
                amount=Decimal("80.00"),
                currency="INR",
                status=PaymentStatus.CREATED,
                provider="mock",
                provider_order_id="order_order-1",
            )
            session.add(payment)
            session.flush()
            payment_ids.append(payment.id)
        session.commit()
        ids = (biz.id, order.id, payment_ids)
    finally:
        session.close()
    try:
        yield ids
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.execute(delete(Payment).where(Payment.business_id == ids[0]))
            cleanup.execute(delete(Order).where(Order.business_id == ids[0]))
            cleanup.execute(delete(Business).where(Business.id == ids[0]))
            cleanup.commit()
        finally:
            cleanup.close()


def _run(tasks: list[tuple[int, str]], business_id: int) -> list[str]:
    """Each task = (payment_id, provider_payment_id); verify concurrently."""
    results: list[str] = ["" for _ in tasks]
    barrier = threading.Barrier(len(tasks))

    def worker(index: int, payment_id: int, pid: str) -> None:
        session = SessionLocal()
        try:
            service = _payment_service(session)
            barrier.wait()
            payment = service.verify(business_id, payment_id, pid, actor_user_id=None)
            results[index] = "ok" if payment.status is PaymentStatus.SUCCESS else "other"
        except PaymentStateError:
            results[index] = "conflict"
        except Exception as exc:  # pragma: no cover
            results[index] = f"error:{exc}"
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker, args=(i, pid, ppid)) for i, (pid, ppid) in enumerate(tasks)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def _order_status(order_id: int) -> str:
    session = SessionLocal()
    try:
        return session.execute(select(Order.status).where(Order.id == order_id)).scalar_one().value
    finally:
        session.close()


def _success_count(order_id: int) -> int:
    session = SessionLocal()
    try:
        return session.execute(
            select(func.count())
            .select_from(Payment)
            .where(Payment.order_id == order_id, Payment.status == PaymentStatus.SUCCESS)
        ).scalar_one()
    finally:
        session.close()


def _movement_count(order_id: int) -> int:
    session = SessionLocal()
    try:
        # Payment must add no stock movements at all.
        inv_id = session.execute(
            select(Inventory.id)
            .join(Order, Order.business_id == Inventory.business_id)
            .where(Order.id == order_id)
        ).scalar_one()
        return session.execute(
            select(func.count())
            .select_from(StockMovement)
            .where(StockMovement.inventory_id == inv_id)
        ).scalar_one()
    finally:
        session.close()


# --- CASE A: duplicate verification of the same payment ---------------------


def test_duplicate_verification_same_payment() -> None:
    with _confirmed_order_with_payments(1) as (biz_id, order_id, pids):
        results = _run([(pids[0], "pay_ok_1"), (pids[0], "pay_ok_1")], biz_id)
        assert results == ["ok", "ok"]  # one real success, one idempotent success
        assert _order_status(order_id) == "PAID"
        assert _success_count(order_id) == 1
        assert _movement_count(order_id) == 0  # payment never touches inventory


# --- CASE B: competing payments for the same order --------------------------


def test_competing_payments_only_one_succeeds() -> None:
    with _confirmed_order_with_payments(2) as (biz_id, order_id, pids):
        results = _run([(pids[0], "pay_ok_a"), (pids[1], "pay_ok_b")], biz_id)
        assert results.count("ok") == 1
        assert results.count("conflict") == 1
        assert _order_status(order_id) == "PAID"
        assert _success_count(order_id) == 1  # one successful payment only
        assert _movement_count(order_id) == 0
