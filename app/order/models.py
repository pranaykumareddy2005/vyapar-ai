"""Order + OrderItem ORM models and the guarded lifecycle state machine.

The status is a guarded state machine (LLD §5.1), not a free-form field: every
transition goes through the ``TRANSITIONS`` table, and illegal jumps are rejected.
Two transitions carry inventory side effects (confirm decrements, cancel-from-
confirmed restores); those are applied by ``OrderService`` inside one transaction.
``OrderItem`` snapshots ``product_name`` and ``unit_price`` at sale.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db_mixins import TimestampMixin
from app.db import Base


class OrderStatus(enum.StrEnum):
    CREATED = "CREATED"
    CONFIRMED = "CONFIRMED"
    PAID = "PAID"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderEvent(enum.StrEnum):
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"
    PAY = "PAY"
    PACK = "PACK"
    SHIP = "SHIP"
    DELIVER = "DELIVER"
    CLOSE = "CLOSE"


class InventoryEffect(enum.Enum):
    """Side effect a transition has on inventory."""

    NONE = "none"
    DECREMENT = "decrement"  # confirm: reserve/consume stock
    RESTORE = "restore"  # cancel after confirm: give stock back


@dataclass(frozen=True, slots=True)
class Transition:
    to: OrderStatus
    effect: InventoryEffect


# The single source of truth for the lifecycle (LLD §5.1). Any (status, event)
# not present here is an illegal transition and is rejected by the service.
TRANSITIONS: dict[tuple[OrderStatus, OrderEvent], Transition] = {
    (OrderStatus.CREATED, OrderEvent.CONFIRM): Transition(
        OrderStatus.CONFIRMED, InventoryEffect.DECREMENT
    ),
    (OrderStatus.CREATED, OrderEvent.CANCEL): Transition(
        OrderStatus.CANCELLED, InventoryEffect.NONE
    ),
    (OrderStatus.CONFIRMED, OrderEvent.PAY): Transition(OrderStatus.PAID, InventoryEffect.NONE),
    (OrderStatus.CONFIRMED, OrderEvent.CANCEL): Transition(
        OrderStatus.CANCELLED, InventoryEffect.RESTORE
    ),
    (OrderStatus.PAID, OrderEvent.PACK): Transition(OrderStatus.PACKED, InventoryEffect.NONE),
    (OrderStatus.PACKED, OrderEvent.SHIP): Transition(OrderStatus.SHIPPED, InventoryEffect.NONE),
    (OrderStatus.SHIPPED, OrderEvent.DELIVER): Transition(
        OrderStatus.DELIVERED, InventoryEffect.NONE
    ),
    (OrderStatus.DELIVERED, OrderEvent.CLOSE): Transition(
        OrderStatus.COMPLETED, InventoryEffect.NONE
    ),
}


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_business_id", "business_id"),
        Index("ix_orders_business_status", "business_id", "status"),
        Index("ix_orders_business_customer", "business_id", "customer_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    # RESTRICT: a customer with orders cannot be hard-deleted (customers are
    # soft-deleted), keeping order history intact.
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customer.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, native_enum=False, length=20), nullable=False
    )
    tax_amt: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_amt: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItem.id",
    )


class OrderItem(TimestampMixin, Base):
    __tablename__ = "order_item"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_item_quantity_positive"),
        Index("ix_order_item_business_order", "business_id", "order_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    # RESTRICT: products are soft-deleted, never hard-deleted, so the reference and
    # the snapshot below both remain valid for historical orders.
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("product.id", ondelete="RESTRICT"), nullable=False
    )
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)  # snapshot
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)  # snapshot
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")

    def line_total(self) -> Decimal:
        result: Decimal = self.unit_price * self.quantity
        return result
