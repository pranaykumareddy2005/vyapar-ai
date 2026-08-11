"""Concurrency test: competing order confirmations against the same stock (§14).

Real PostgreSQL, separate connections/threads. Order confirmation consumes stock
through InventoryService's ``FOR UPDATE`` row lock (reused, not re-implemented), so
two orders cannot oversell. SQLite is deliberately not used.
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
from app.common.exceptions import InsufficientStockError
from app.common.security import Role
from app.customer.models import Customer
from app.customer.repository import CustomerRepository
from app.db import SessionLocal
from app.inventory.models import Inventory, StockMovement
from app.inventory.repository import InventoryRepository, StockMovementRepository
from app.inventory.service import InventoryService
from app.order.models import Order, OrderEvent, OrderItem, OrderStatus
from app.order.repository import OrderItemRepository, OrderRepository
from app.order.service import OrderService
from sqlalchemy import delete, func, select


def _order_service(session: object) -> OrderService:
    inventory = InventoryService(
        session,  # type: ignore[arg-type]
        InventoryRepository(session),  # type: ignore[arg-type]
        StockMovementRepository(session),  # type: ignore[arg-type]
        ProductRepository(session),  # type: ignore[arg-type]
        events=EventBus(),
    )
    return OrderService(
        session,  # type: ignore[arg-type]
        OrderRepository(session),  # type: ignore[arg-type]
        OrderItemRepository(session),  # type: ignore[arg-type]
        CustomerRepository(session),  # type: ignore[arg-type]
        ProductRepository(session),  # type: ignore[arg-type]
        inventory,
        tax_rate=Decimal("0"),
        events=EventBus(),
    )


@contextmanager
def _two_orders(stock: int, qty_a: int, qty_b: int) -> Iterator[tuple[int, int, int, int]]:
    """Create a product with ``stock`` and two CREATED orders; yield ids and cleanup."""
    session = SessionLocal()
    try:
        biz = Business(
            name="OrdConc", category="grocery", contact_number="+910000000000", address="a"
        )
        session.add(biz)
        session.flush()
        session.add(
            User(business_id=biz.id, email=f"oc-{biz.id}@x.co", password_hash="x", role=Role.OWNER)
        )
        product = Product(
            business_id=biz.id, name="P", price_amt=Decimal("10.00"), sku=f"OC-{biz.id}"
        )
        session.add(product)
        session.flush()
        inv = Inventory(
            business_id=biz.id, product_id=product.id, quantity=stock, low_stock_threshold=0
        )
        session.add(inv)
        customer = Customer(business_id=biz.id, name="C", phone=f"+9100{biz.id}")
        session.add(customer)
        session.flush()
        order_ids = []
        for qty in (qty_a, qty_b):
            order = Order(
                business_id=biz.id,
                customer_id=customer.id,
                status=OrderStatus.CREATED,
                tax_amt=Decimal("0.00"),
                total_amt=Decimal(str(10 * qty)),
            )
            session.add(order)
            session.flush()
            session.add(
                OrderItem(
                    business_id=biz.id,
                    order_id=order.id,
                    product_id=product.id,
                    product_name="P",
                    unit_price=Decimal("10.00"),
                    quantity=qty,
                )
            )
            order_ids.append(order.id)
        session.commit()
        ids = (biz.id, inv.id, order_ids[0], order_ids[1])
    finally:
        session.close()
    try:
        yield ids
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.execute(delete(Order).where(Order.business_id == ids[0]))
            cleanup.execute(delete(Business).where(Business.id == ids[0]))
            cleanup.commit()
        finally:
            cleanup.close()


def _confirm_concurrently(business_id: int, order_a: int, order_b: int) -> list[str]:
    results: list[str] = ["", ""]
    barrier = threading.Barrier(2)

    def worker(index: int, order_id: int) -> None:
        session = SessionLocal()
        try:
            service = _order_service(session)
            barrier.wait()
            service.transition(business_id, order_id, OrderEvent.CONFIRM, actor_user_id=None)
            results[index] = "ok"
        except InsufficientStockError:
            results[index] = "insufficient"
        except Exception as exc:  # pragma: no cover
            results[index] = f"error:{exc}"
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker, args=(0, order_a)),
        threading.Thread(target=worker, args=(1, order_b)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def _final_stock(inventory_id: int) -> int:
    session = SessionLocal()
    try:
        return session.execute(
            select(Inventory.quantity).where(Inventory.id == inventory_id)
        ).scalar_one()
    finally:
        session.close()


def _sale_movements(inventory_id: int) -> int:
    session = SessionLocal()
    try:
        return session.execute(
            select(func.count())
            .select_from(StockMovement)
            .where(StockMovement.inventory_id == inventory_id)
        ).scalar_one()
    finally:
        session.close()


def test_competing_confirmations_do_not_oversell() -> None:
    # Stock 10; order A wants 7, order B wants 5 -> both cannot succeed.
    with _two_orders(10, 7, 5) as (biz_id, inv_id, order_a, order_b):
        results = _confirm_concurrently(biz_id, order_a, order_b)
        assert results.count("ok") == 1
        assert results.count("insufficient") == 1
        final = _final_stock(inv_id)
        assert final in (3, 5)  # winner-dependent, never negative, never both
        assert final >= 0
        assert _sale_movements(inv_id) == 1  # exactly one confirmed order consumed stock


def test_both_confirm_when_stock_sufficient() -> None:
    # Stock 10; A wants 4, B wants 5 -> both fit (sum 9 <= 10).
    with _two_orders(10, 4, 5) as (biz_id, inv_id, order_a, order_b):
        results = _confirm_concurrently(biz_id, order_a, order_b)
        assert results == ["ok", "ok"]
        assert _final_stock(inv_id) == 1
        assert _sale_movements(inv_id) == 2
