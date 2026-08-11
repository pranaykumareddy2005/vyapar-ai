"""Order application service - totals, lifecycle state machine, inventory sync.

Totals are computed server-side with the ``Money`` value object (never from client
input, never float). Order confirmation decrements inventory and cancellation of a
confirmed order restores it, both through ``InventoryService`` inside a single order
transaction so the status change and all stock writes commit atomically. The
guarded ``TRANSITIONS`` table rejects illegal state changes and makes double stock
restoration impossible (CANCELLED is terminal).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from app.catalog.repository import ProductRepository
from app.common.events import (
    DomainEvent,
    EventBus,
    LowStock,
    OrderCancelled,
    OrderConfirmed,
    OrderCreated,
    event_bus,
)
from app.common.exceptions import ConflictError, NotFoundError, ValidationError
from app.common.money import Money
from app.customer.repository import CustomerRepository
from app.inventory.models import MovementType
from app.inventory.service import InventoryService
from app.order.models import (
    TRANSITIONS,
    InventoryEffect,
    Order,
    OrderEvent,
    OrderItem,
    OrderStatus,
)
from app.order.repository import OrderItemRepository, OrderRepository
from app.order.schemas import OrderCreate

logger = logging.getLogger(__name__)


def compute_order_totals(
    lines: list[tuple[Decimal, int]], tax_rate: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    """Return (subtotal, tax, total) as Decimals using exact Money arithmetic.

    ``goods = Σ(unit_price · qty)``, ``tax = goods · tax_rate`` (rounded to cents),
    ``total = goods + tax`` (LLD §7.3).
    """
    subtotal = Money.zero()
    for unit_price, quantity in lines:
        subtotal = subtotal + Money(unit_price) * quantity
    tax = subtotal * tax_rate
    total = subtotal + tax
    return subtotal.amount, tax.amount, total.amount


class OrderService:
    def __init__(
        self,
        session: Session,
        orders: OrderRepository,
        order_items: OrderItemRepository,
        customers: CustomerRepository,
        products: ProductRepository,
        inventory: InventoryService,
        *,
        tax_rate: Decimal,
        events: EventBus = event_bus,
    ) -> None:
        self._session = session
        self._orders = orders
        self._items = order_items
        self._customers = customers
        self._products = products
        self._inventory = inventory
        self._tax_rate = tax_rate
        self._events = events

    # --- creation ---------------------------------------------------------

    def create_order(self, business_id: int, payload: OrderCreate) -> Order:
        if self._customers.get(business_id, payload.customer_id) is None:
            raise NotFoundError("customer not found")

        item_models: list[OrderItem] = []
        lines: list[tuple[Decimal, int]] = []
        for line in payload.items:
            # ProductRepository.get excludes soft-deleted products, so a deleted or
            # foreign product is rejected for a NEW order (plan item 18).
            product = self._products.get(business_id, line.product_id)
            if product is None:
                raise ValidationError("product not found or unavailable for this business")
            item_models.append(
                OrderItem(
                    business_id=business_id,
                    product_id=product.id,
                    product_name=product.name,  # snapshot
                    unit_price=product.price_amt,  # snapshot
                    quantity=line.quantity,
                )
            )
            lines.append((product.price_amt, line.quantity))

        _subtotal, tax, total = compute_order_totals(lines, self._tax_rate)

        try:
            order = self._orders.add(
                Order(
                    business_id=business_id,
                    customer_id=payload.customer_id,
                    status=OrderStatus.CREATED,
                    tax_amt=tax,
                    total_amt=total,
                )
            )
            for item in item_models:
                item.order_id = order.id
                self._items.add(item)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

        self._session.refresh(order)
        self._events.publish(
            OrderCreated(business_id=business_id, order_id=order.id, customer_id=order.customer_id)
        )
        return order

    # --- queries ----------------------------------------------------------

    def get_order(self, business_id: int, order_id: int) -> Order:
        order = self._orders.get(business_id, order_id)
        if order is None:
            raise NotFoundError("order not found")
        return order

    def list_orders(self, business_id: int) -> list[Order]:
        return self._orders.list(business_id)

    # --- lifecycle --------------------------------------------------------

    def transition(
        self, business_id: int, order_id: int, event: OrderEvent, *, actor_user_id: int | None
    ) -> Order:
        order = self.get_order(business_id, order_id)
        rule = TRANSITIONS.get((order.status, event))
        if rule is None:
            raise ConflictError(f"cannot apply {event.value} to an order in {order.status.value}")

        pending: list[DomainEvent] = []
        try:
            if rule.effect is InventoryEffect.DECREMENT:
                pending.extend(
                    self._apply_inventory(business_id, order, sign=-1, actor_user_id=actor_user_id)
                )
            elif rule.effect is InventoryEffect.RESTORE:
                pending.extend(
                    self._apply_inventory(business_id, order, sign=1, actor_user_id=actor_user_id)
                )

            order.status = rule.to
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

        self._session.refresh(order)
        # Publish only after a successful commit.
        for pending_event in pending:
            self._events.publish(pending_event)
        self._publish_lifecycle(order, rule.to)
        return order

    def _apply_inventory(
        self, business_id: int, order: Order, *, sign: int, actor_user_id: int | None
    ) -> list[LowStock]:
        """Stage a stock change for every line (no commit); return low-stock events.

        ``sign=-1`` decrements (SALE, on confirm); ``sign=+1`` restores (RESTOCK, on
        cancel). All staged writes commit atomically with the status change.
        """
        movement = MovementType.SALE if sign < 0 else MovementType.RESTOCK
        events: list[LowStock] = []
        for item in order.items:
            pending = self._inventory.stage_adjustment(
                business_id,
                item.product_id,
                delta=sign * item.quantity,
                movement_type=movement,
                actor_user_id=actor_user_id,
            )
            if pending is not None:
                events.append(pending)
        return events

    def _publish_lifecycle(self, order: Order, new_status: OrderStatus) -> None:
        if new_status is OrderStatus.CONFIRMED:
            self._events.publish(
                OrderConfirmed(
                    business_id=order.business_id,
                    order_id=order.id,
                    customer_id=order.customer_id,
                )
            )
        elif new_status is OrderStatus.CANCELLED:
            self._events.publish(
                OrderCancelled(
                    business_id=order.business_id,
                    order_id=order.id,
                    customer_id=order.customer_id,
                )
            )
