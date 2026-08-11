"""Inventory persistence. Every query is tenant-scoped by ``business_id``.

Repositories are persistence-only: no negative-stock checks, no low-stock logic,
no calculations (those live in :class:`InventoryService`). The one concurrency
primitive exposed here is :meth:`InventoryRepository.lock_for_update`, which
issues ``SELECT ... FOR UPDATE`` so the service can hold a real PostgreSQL row
lock across the read-modify-write.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.inventory.models import Inventory, StockMovement


class InventoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, inventory: Inventory) -> Inventory:
        self._session.add(inventory)
        self._session.flush()
        return inventory

    def get(self, business_id: int, inventory_id: int) -> Inventory | None:
        stmt = select(Inventory).where(
            Inventory.id == inventory_id, Inventory.business_id == business_id
        )
        return self._session.scalars(stmt).one_or_none()

    def get_by_product(self, business_id: int, product_id: int) -> Inventory | None:
        stmt = select(Inventory).where(
            Inventory.product_id == product_id, Inventory.business_id == business_id
        )
        return self._session.scalars(stmt).one_or_none()

    def lock_for_update(self, business_id: int, inventory_id: int) -> Inventory | None:
        """Return the inventory row under a ``SELECT ... FOR UPDATE`` row lock.

        The lock is held until the surrounding transaction commits/rolls back, so
        the service can safely read the current quantity and write the new one
        without a concurrent transaction interleaving.
        """
        stmt = (
            select(Inventory)
            .where(Inventory.id == inventory_id, Inventory.business_id == business_id)
            .with_for_update()
        )
        return self._session.scalars(stmt).one_or_none()

    def lock_for_update_by_product(self, business_id: int, product_id: int) -> Inventory | None:
        """Row-lock the inventory for a product (``SELECT ... FOR UPDATE``).

        Used by order confirmation to lock stock by product id within the order
        transaction; the lock is held until that transaction commits.
        """
        stmt = (
            select(Inventory)
            .where(Inventory.product_id == product_id, Inventory.business_id == business_id)
            .with_for_update()
        )
        return self._session.scalars(stmt).one_or_none()

    def exists_for_product(self, business_id: int, product_id: int) -> bool:
        stmt = select(Inventory.id).where(
            Inventory.business_id == business_id, Inventory.product_id == product_id
        )
        return self._session.scalars(stmt).first() is not None

    def list(self, business_id: int) -> list[Inventory]:
        stmt = select(Inventory).where(Inventory.business_id == business_id).order_by(Inventory.id)
        return list(self._session.scalars(stmt).all())


class StockMovementRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, movement: StockMovement) -> StockMovement:
        self._session.add(movement)
        self._session.flush()
        return movement

    def list_for_inventory(self, business_id: int, inventory_id: int) -> list[StockMovement]:
        stmt = (
            select(StockMovement)
            .where(
                StockMovement.business_id == business_id,
                StockMovement.inventory_id == inventory_id,
            )
            .order_by(StockMovement.id)
        )
        return list(self._session.scalars(stmt).all())
