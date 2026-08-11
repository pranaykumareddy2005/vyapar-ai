"""Concurrency tests: real PostgreSQL row-locking under contention (§8, §22).

These tests do NOT use the rolled-back ``db_session`` fixture. They commit real
rows and spawn threads, each with its OWN Session/connection, so that
``SELECT ... FOR UPDATE`` in :meth:`InventoryService.adjust_stock` is exercised
against genuinely concurrent transactions. Every test cleans up by deleting its
throwaway business (cascade). SQLite is deliberately not used - Postgres is
required for real row locks.
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
from app.db import SessionLocal
from app.inventory.models import Inventory, MovementType, StockMovement
from app.inventory.repository import InventoryRepository, StockMovementRepository
from app.inventory.service import InventoryService
from sqlalchemy import delete, func, select


@contextmanager
def temp_inventory(initial_qty: int, threshold: int = 0) -> Iterator[tuple[int, int]]:
    """Create a committed business/product/inventory; yield (business_id, inventory_id)."""
    session = SessionLocal()
    try:
        biz = Business(
            name="ConcShop", category="grocery", contact_number="+910000000000", address="a"
        )
        session.add(biz)
        session.flush()
        session.add(
            User(
                business_id=biz.id,
                email=f"conc-{biz.id}@shop.co",
                password_hash="x",
                role=Role.OWNER,
            )
        )
        product = Product(
            business_id=biz.id, name="P", price_amt=Decimal("1.00"), sku=f"C-{biz.id}"
        )
        session.add(product)
        session.flush()
        inventory = Inventory(
            business_id=biz.id,
            product_id=product.id,
            quantity=initial_qty,
            low_stock_threshold=threshold,
        )
        session.add(inventory)
        session.flush()
        session.commit()
        ids = (biz.id, inventory.id)
    finally:
        session.close()
    try:
        yield ids
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.execute(delete(Business).where(Business.id == ids[0]))
            cleanup.commit()
        finally:
            cleanup.close()


def _run_concurrent(business_id: int, inventory_id: int, deltas: list[int]) -> list[str]:
    """Run one adjust_stock per delta, each on its own thread/Session, all released
    simultaneously via a barrier. Returns per-thread outcomes."""
    results: list[str] = ["" for _ in deltas]
    barrier = threading.Barrier(len(deltas))

    def worker(index: int, delta: int) -> None:
        session = SessionLocal()
        try:
            service = InventoryService(
                session,
                InventoryRepository(session),
                StockMovementRepository(session),
                ProductRepository(session),
                events=EventBus(),  # throwaway bus; no global side effects
            )
            barrier.wait()
            service.adjust_stock(
                business_id,
                inventory_id,
                delta=delta,
                movement_type=MovementType.MANUAL_ADJUSTMENT,
            )
            results[index] = "ok"
        except InsufficientStockError:
            results[index] = "insufficient"
        except Exception as exc:  # pragma: no cover - surfaces unexpected failures
            results[index] = f"error:{exc}"
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(i, d)) for i, d in enumerate(deltas)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


def _final_quantity(inventory_id: int) -> int:
    session = SessionLocal()
    try:
        return session.execute(
            select(Inventory.quantity).where(Inventory.id == inventory_id)
        ).scalar_one()
    finally:
        session.close()


def _movement_count(inventory_id: int) -> int:
    session = SessionLocal()
    try:
        return session.execute(
            select(func.count())
            .select_from(StockMovement)
            .where(StockMovement.inventory_id == inventory_id)
        ).scalar_one()
    finally:
        session.close()


# --- TEST 1: concurrent decrease (no oversell) ------------------------------


def test_concurrent_decrease_one_succeeds_no_oversell() -> None:
    with temp_inventory(10) as (biz_id, inv_id):
        results = _run_concurrent(biz_id, inv_id, [-7, -5])
        assert results.count("ok") == 1
        assert results.count("insufficient") == 1
        final = _final_quantity(inv_id)
        # Whichever transaction won the lock: final is 3 (-7 won) or 5 (-5 won).
        # Never negative, never both applied.
        assert final in (3, 5)
        assert final >= 0
        assert _movement_count(inv_id) == 1  # exactly one successful movement


# --- TEST 2: concurrent restock (lost-update safety) ------------------------


def test_concurrent_restock_sums_correctly() -> None:
    with temp_inventory(10) as (biz_id, inv_id):
        results = _run_concurrent(biz_id, inv_id, [5, 7])
        assert results == ["ok", "ok"]
        assert _final_quantity(inv_id) == 22  # no lost update
        assert _movement_count(inv_id) == 2


# --- TEST 3: mixed operations (serializable result) -------------------------


def test_concurrent_mixed_operations() -> None:
    deltas = [10, -5, 7, -3, 4]  # all safe from a base of 100
    with temp_inventory(100) as (biz_id, inv_id):
        results = _run_concurrent(biz_id, inv_id, deltas)
        assert results == ["ok"] * len(deltas)
        assert _final_quantity(inv_id) == 100 + sum(deltas)
        assert _movement_count(inv_id) == len(deltas)


# --- TEST 4: never negative under heavy contention --------------------------


def test_concurrent_decrease_never_goes_negative() -> None:
    with temp_inventory(5) as (biz_id, inv_id):
        results = _run_concurrent(biz_id, inv_id, [-3, -3, -3, -3, -3])
        assert results.count("ok") == 1  # 5 - 3 = 2; every other -3 rejected
        assert results.count("insufficient") == 4
        final = _final_quantity(inv_id)
        assert final == 2
        assert final >= 0
        assert _movement_count(inv_id) == 1


# --- TEST 5: movement consistency (one per successful change) ---------------


def test_movement_count_matches_successful_changes() -> None:
    deltas = [8, -2, -20, 5, -1]  # -20 will be rejected from a low balance
    with temp_inventory(6) as (biz_id, inv_id):
        results = _run_concurrent(biz_id, inv_id, deltas)
        successes = results.count("ok")
        # Every successful change has exactly one movement; rejects have none.
        assert _movement_count(inv_id) == successes
        # Final equals the base plus the sum of only the successful deltas, and is
        # never negative.
        final = _final_quantity(inv_id)
        assert final >= 0
        assert final == 6 + sum(d for d, r in zip(deltas, results, strict=True) if r == "ok")
