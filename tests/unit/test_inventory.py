"""Unit tests: inventory schema validation, low-stock rule, movement types."""

from __future__ import annotations

import pytest
from app.inventory.models import Inventory, MovementType
from app.inventory.schemas import (
    InventoryCreate,
    InventoryOut,
    StockAdjust,
    ThresholdUpdate,
)
from pydantic import ValidationError

# --- schema validation ------------------------------------------------------


def test_stock_adjust_accepts_signed_delta() -> None:
    assert StockAdjust(delta=-5, movement_type=MovementType.SALE).delta == -5
    assert StockAdjust(delta=20, movement_type="RESTOCK").movement_type is MovementType.RESTOCK


def test_stock_adjust_rejects_unknown_movement_type() -> None:
    with pytest.raises(ValidationError):
        StockAdjust(delta=1, movement_type="GIFT")  # type: ignore[arg-type]


def test_stock_adjust_rejects_out_of_range_delta() -> None:
    with pytest.raises(ValidationError):
        StockAdjust(delta=10_000_000, movement_type=MovementType.RESTOCK)


def test_inventory_create_rejects_negative_quantity() -> None:
    with pytest.raises(ValidationError):
        InventoryCreate(product_id=1, quantity=-1)
    with pytest.raises(ValidationError):
        InventoryCreate(product_id=1, low_stock_threshold=-1)


def test_threshold_update_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        ThresholdUpdate(low_stock_threshold=-1)


# --- low-stock rule: quantity <= threshold ----------------------------------


@pytest.mark.parametrize(
    ("quantity", "threshold", "expected"),
    [
        (5, 5, True),  # equal -> low (boundary is <=, not <)
        (4, 5, True),  # below -> low
        (6, 5, False),  # above -> not low
        (0, 0, True),  # empty -> low
    ],
)
def test_is_low_boundary(quantity: int, threshold: int, expected: bool) -> None:
    inv = Inventory(quantity=quantity, low_stock_threshold=threshold)
    assert inv.is_low() is expected


def test_inventory_out_maps_low_stock_flag() -> None:
    inv = Inventory(id=1, business_id=1, product_id=1, quantity=2, low_stock_threshold=3)
    out = InventoryOut.from_model(inv)
    assert out.low_stock is True
    assert out.quantity == 2


def test_movement_types_are_the_approved_four() -> None:
    assert {m.value for m in MovementType} == {
        "RESTOCK",
        "SALE",
        "MANUAL_ADJUSTMENT",
        "DAMAGE",
    }
