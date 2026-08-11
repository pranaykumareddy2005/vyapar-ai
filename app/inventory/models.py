"""Inventory ORM models: Inventory + append-only StockMovement.

Both are tenant-scoped by ``business_id``. ``Inventory`` holds the integer stock
quantity and the configurable low-stock threshold; a partial ``CHECK`` keeps
quantity non-negative as a database backstop to the service's transactional
guard. ``StockMovement`` is immutable history - it is only ever inserted, never
updated (corrections are new compensating movements). No quantity column lives on
``Product`` (the Phase-3 product/stock separation is preserved).
"""

from __future__ import annotations

import enum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db_mixins import TimestampMixin
from app.db import Base


class MovementType(enum.StrEnum):
    """Stock movement reasons (SDD/LLD §10) - deliberately small."""

    RESTOCK = "RESTOCK"
    SALE = "SALE"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    DAMAGE = "DAMAGE"


class Inventory(TimestampMixin, Base):
    __tablename__ = "inventory"
    __table_args__ = (
        # One inventory record per product (LLD composition, enforced in DB).
        UniqueConstraint("product_id", name="uq_inventory_product_id"),
        CheckConstraint("quantity >= 0", name="ck_inventory_quantity_non_negative"),
        CheckConstraint("low_stock_threshold >= 0", name="ck_inventory_threshold_non_negative"),
        Index("ix_inventory_business_id", "business_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("product.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    low_stock_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    def is_low(self) -> bool:
        """True when stock is at or below the threshold (quantity <= threshold)."""
        return self.quantity <= self.low_stock_threshold


class StockMovement(TimestampMixin, Base):
    __tablename__ = "stock_movement"
    __table_args__ = (
        CheckConstraint("delta <> 0", name="ck_stock_movement_delta_nonzero"),
        CheckConstraint("resulting_quantity >= 0", name="ck_stock_movement_result_non_negative"),
        Index("ix_stock_movement_business_inventory", "business_id", "inventory_id"),
        Index("ix_stock_movement_business_id", "business_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    inventory_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("inventory.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized product reference (matches LLD append(productId, ...) and
    # supports per-product history without a join).
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("product.id", ondelete="CASCADE"), nullable=False
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    movement_type: Mapped[MovementType] = mapped_column(
        SAEnum(MovementType, native_enum=False, length=20), nullable=False
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
