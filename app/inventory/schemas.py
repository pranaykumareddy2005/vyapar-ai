"""Pydantic v2 schemas for the inventory API edge.

ORM models are never returned directly. Quantities and deltas are integers
(never float); deltas are validated non-zero at the edge, with the authoritative
business rules enforced by the service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from app.inventory.models import MovementType

if TYPE_CHECKING:
    from app.inventory.models import Inventory


class InventoryCreate(BaseModel):
    product_id: int
    quantity: int = Field(default=0, ge=0)
    low_stock_threshold: int = Field(default=0, ge=0)


class ThresholdUpdate(BaseModel):
    low_stock_threshold: int = Field(ge=0)


class StockAdjust(BaseModel):
    # Signed delta; zero is rejected (no meaningless history). Bounded to a sane
    # range to reject obviously malformed input.
    delta: int = Field(ge=-1_000_000, le=1_000_000)
    movement_type: MovementType

    def is_zero(self) -> bool:
        return self.delta == 0


class InventoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    product_id: int
    quantity: int
    low_stock_threshold: int
    low_stock: bool

    @classmethod
    def from_model(cls, inv: Inventory) -> InventoryOut:
        return cls(
            id=inv.id,
            business_id=inv.business_id,
            product_id=inv.product_id,
            quantity=inv.quantity,
            low_stock_threshold=inv.low_stock_threshold,
            low_stock=inv.is_low(),
        )


class StockMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    inventory_id: int
    product_id: int
    delta: int
    resulting_quantity: int
    movement_type: MovementType
    actor_user_id: int | None
