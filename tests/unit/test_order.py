"""Unit tests: order totals, state-machine table, and schema validation."""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.order.models import (
    TRANSITIONS,
    InventoryEffect,
    OrderEvent,
    OrderStatus,
)
from app.order.schemas import OrderCreate, OrderItemIn
from app.order.service import compute_order_totals
from pydantic import ValidationError

# --- money / totals ---------------------------------------------------------


def test_totals_no_tax() -> None:
    subtotal, tax, total = compute_order_totals(
        [(Decimal("40.00"), 2), (Decimal("15.50"), 3)], Decimal("0")
    )
    assert subtotal == Decimal("126.50")
    assert tax == Decimal("0.00")
    assert total == Decimal("126.50")


def test_totals_with_tax_rounds_to_cents() -> None:
    subtotal, tax, total = compute_order_totals([(Decimal("99.99"), 1)], Decimal("0.18"))
    assert subtotal == Decimal("99.99")
    assert tax == Decimal("18.00")  # 17.9982 -> 18.00 (half-up, 2dp)
    assert total == Decimal("117.99")


def test_totals_are_decimal_not_float() -> None:
    _s, _t, total = compute_order_totals([(Decimal("0.10"), 3)], Decimal("0"))
    assert total == Decimal("0.30")  # exact, no float drift
    assert isinstance(total, Decimal)


# --- state machine ----------------------------------------------------------


def test_confirm_and_cancel_effects() -> None:
    confirm = TRANSITIONS[(OrderStatus.CREATED, OrderEvent.CONFIRM)]
    assert confirm.to is OrderStatus.CONFIRMED
    assert confirm.effect is InventoryEffect.DECREMENT

    cancel_confirmed = TRANSITIONS[(OrderStatus.CONFIRMED, OrderEvent.CANCEL)]
    assert cancel_confirmed.to is OrderStatus.CANCELLED
    assert cancel_confirmed.effect is InventoryEffect.RESTORE

    cancel_created = TRANSITIONS[(OrderStatus.CREATED, OrderEvent.CANCEL)]
    assert cancel_created.effect is InventoryEffect.NONE  # nothing to restore


def test_full_happy_path_exists() -> None:
    chain = [
        (OrderStatus.CREATED, OrderEvent.CONFIRM, OrderStatus.CONFIRMED),
        (OrderStatus.CONFIRMED, OrderEvent.PAY, OrderStatus.PAID),
        (OrderStatus.PAID, OrderEvent.PACK, OrderStatus.PACKED),
        (OrderStatus.PACKED, OrderEvent.SHIP, OrderStatus.SHIPPED),
        (OrderStatus.SHIPPED, OrderEvent.DELIVER, OrderStatus.DELIVERED),
        (OrderStatus.DELIVERED, OrderEvent.CLOSE, OrderStatus.COMPLETED),
    ]
    for src, event, dst in chain:
        assert TRANSITIONS[(src, event)].to is dst


@pytest.mark.parametrize(
    ("status", "event"),
    [
        (OrderStatus.CANCELLED, OrderEvent.CANCEL),  # terminal: no double cancel/restore
        (OrderStatus.COMPLETED, OrderEvent.CANCEL),  # terminal
        (OrderStatus.CREATED, OrderEvent.SHIP),  # illegal jump
        (OrderStatus.DELIVERED, OrderEvent.CONFIRM),  # cannot go backwards
        (OrderStatus.CREATED, OrderEvent.PAY),  # must confirm first
    ],
)
def test_illegal_transitions_absent(status: OrderStatus, event: OrderEvent) -> None:
    assert (status, event) not in TRANSITIONS


# --- schema validation ------------------------------------------------------


def test_order_requires_at_least_one_item() -> None:
    with pytest.raises(ValidationError):
        OrderCreate(customer_id=1, items=[])


def test_order_item_quantity_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        OrderItemIn(product_id=1, quantity=0)
    with pytest.raises(ValidationError):
        OrderItemIn(product_id=1, quantity=-2)
