"""Inventory application service - the single authority for stock mutations.

Every change to ``inventory.quantity`` goes through :meth:`adjust_stock`, which
holds a PostgreSQL row lock (``SELECT ... FOR UPDATE``) across the read-modify-
write so concurrent adjustments cannot oversell or race. No other module may
modify ``inventory.quantity`` directly; a future ``OrderService`` or Conversation
handler calls :meth:`adjust_stock` / :meth:`adjust_stock_by_product`.

Low-stock events are published *after* a successful commit (never for a rolled-
back change). See docs/phase5_schema_decision.md §4 for the event/commit ordering
and its one documented limitation.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalog.repository import ProductRepository
from app.common.events import EventBus, LowStock, event_bus
from app.common.exceptions import (
    ConflictError,
    InsufficientStockError,
    NotFoundError,
    ValidationError,
)
from app.inventory.models import Inventory, MovementType, StockMovement
from app.inventory.repository import InventoryRepository, StockMovementRepository

logger = logging.getLogger(__name__)


class InventoryService:
    def __init__(
        self,
        session: Session,
        inventory: InventoryRepository,
        movements: StockMovementRepository,
        products: ProductRepository,
        events: EventBus = event_bus,
    ) -> None:
        self._session = session
        self._inventory = inventory
        self._movements = movements
        self._products = products
        self._events = events

    # --- creation / queries ----------------------------------------------

    def create_inventory(
        self,
        business_id: int,
        product_id: int,
        *,
        quantity: int = 0,
        low_stock_threshold: int = 0,
    ) -> Inventory:
        """Initialize the (single) inventory record for a business's product.

        Validates product ownership through the Catalog product repository, so a
        foreign or non-existent product is rejected tenant-safely (404).
        """
        if self._products.get(business_id, product_id) is None:
            raise NotFoundError("product not found")
        if self._inventory.exists_for_product(business_id, product_id):
            raise ConflictError("inventory already exists for this product")
        try:
            inventory = self._inventory.add(
                Inventory(
                    business_id=business_id,
                    product_id=product_id,
                    quantity=quantity,
                    low_stock_threshold=low_stock_threshold,
                )
            )
            self._session.commit()
        except IntegrityError as exc:
            # Backstop for a concurrent insert racing the existence check.
            self._session.rollback()
            raise ConflictError("inventory already exists for this product") from exc
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(inventory)
        return inventory

    def get_inventory(self, business_id: int, inventory_id: int) -> Inventory:
        return self._require(business_id, inventory_id)

    def get_inventory_by_product(self, business_id: int, product_id: int) -> Inventory:
        inventory = self._inventory.get_by_product(business_id, product_id)
        if inventory is None:
            raise NotFoundError("inventory not found")
        return inventory

    def list_inventory(self, business_id: int) -> list[Inventory]:
        return self._inventory.list(business_id)

    def list_movements(self, business_id: int, inventory_id: int) -> list[StockMovement]:
        # Ownership check keeps cross-tenant inventory ids from leaking history.
        self._require(business_id, inventory_id)
        return self._movements.list_for_inventory(business_id, inventory_id)

    def update_threshold(
        self, business_id: int, inventory_id: int, low_stock_threshold: int
    ) -> Inventory:
        if low_stock_threshold < 0:
            raise ValidationError("low_stock_threshold must be non-negative")
        inventory = self._require(business_id, inventory_id)
        try:
            inventory.low_stock_threshold = low_stock_threshold
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(inventory)
        return inventory

    # --- the single write authority --------------------------------------

    def adjust_stock(
        self,
        business_id: int,
        inventory_id: int,
        *,
        delta: int,
        movement_type: MovementType,
        actor_user_id: int | None = None,
    ) -> Inventory:
        """Atomically apply a signed stock ``delta`` under a row lock.

        Rejects a zero delta and any change that would drive quantity negative;
        on success writes exactly one immutable ``StockMovement`` and, after the
        commit, publishes ``LowStock`` when ``quantity <= low_stock_threshold``.
        """
        if delta == 0:
            raise ValidationError("delta must be non-zero")

        try:
            inventory = self._inventory.lock_for_update(business_id, inventory_id)
            if inventory is None:
                raise NotFoundError("inventory not found")
            new_quantity = inventory.quantity + delta
            if new_quantity < 0:
                raise InsufficientStockError("insufficient stock for this adjustment")

            inventory.quantity = new_quantity
            self._movements.add(
                StockMovement(
                    business_id=business_id,
                    inventory_id=inventory.id,
                    product_id=inventory.product_id,
                    delta=delta,
                    resulting_quantity=new_quantity,
                    movement_type=movement_type,
                    actor_user_id=actor_user_id,
                )
            )
            # Capture values for the post-commit event before the session expires.
            product_id = inventory.product_id
            threshold = inventory.low_stock_threshold
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

        self._session.refresh(inventory)
        logger.info(
            "stock adjusted business_id=%s product_id=%s delta=%s resulting=%s type=%s",
            business_id,
            product_id,
            delta,
            new_quantity,
            movement_type.value,
        )
        # Publish only after a successful commit so an event is never emitted for
        # a rolled-back change.
        if new_quantity <= threshold:
            self._events.publish(
                LowStock(
                    business_id=business_id,
                    product_id=product_id,
                    quantity=new_quantity,
                    threshold=threshold,
                )
            )
        return inventory

    def stage_adjustment(
        self,
        business_id: int,
        product_id: int,
        *,
        delta: int,
        movement_type: MovementType,
        actor_user_id: int | None = None,
    ) -> LowStock | None:
        """Apply a locked stock adjustment **without committing** and return any
        pending low-stock event.

        A composable primitive for callers (e.g. ``OrderService``) that need to
        stage several adjustments plus their own writes inside one transaction and
        commit exactly once. It preserves the row-lock and non-negative guarantees
        of :meth:`adjust_stock`; the caller owns the commit and must publish the
        returned event only after that commit succeeds.
        """
        if delta == 0:
            raise ValidationError("delta must be non-zero")
        inventory = self._inventory.lock_for_update_by_product(business_id, product_id)
        if inventory is None:
            raise NotFoundError("inventory not found")
        new_quantity = inventory.quantity + delta
        if new_quantity < 0:
            raise InsufficientStockError("insufficient stock for this adjustment")

        inventory.quantity = new_quantity
        self._movements.add(
            StockMovement(
                business_id=business_id,
                inventory_id=inventory.id,
                product_id=product_id,
                delta=delta,
                resulting_quantity=new_quantity,
                movement_type=movement_type,
                actor_user_id=actor_user_id,
            )
        )
        if new_quantity <= inventory.low_stock_threshold:
            return LowStock(
                business_id=business_id,
                product_id=product_id,
                quantity=new_quantity,
                threshold=inventory.low_stock_threshold,
            )
        return None

    def adjust_stock_by_product(
        self,
        business_id: int,
        product_id: int,
        *,
        delta: int,
        movement_type: MovementType,
        actor_user_id: int | None = None,
    ) -> Inventory:
        """Product-keyed entry point for future callers (orders, conversation)."""
        inventory = self.get_inventory_by_product(business_id, product_id)
        return self.adjust_stock(
            business_id,
            inventory.id,
            delta=delta,
            movement_type=movement_type,
            actor_user_id=actor_user_id,
        )

    # --- helpers ----------------------------------------------------------

    def _require(self, business_id: int, inventory_id: int) -> Inventory:
        inventory = self._inventory.get(business_id, inventory_id)
        if inventory is None:
            raise NotFoundError("inventory not found")
        return inventory
