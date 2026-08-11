from __future__ import annotations

from decimal import Decimal

import pytest
from app.common.money import Money


def test_quantizes_to_two_places() -> None:
    assert Money(Decimal("10.005")).amount == Decimal("10.01")


def test_add_and_subtract() -> None:
    assert (Money(Decimal("10")) + Money(Decimal("5"))).amount == Decimal("15.00")
    assert (Money(Decimal("10")) - Money(Decimal("5"))).amount == Decimal("5.00")


def test_multiply_by_quantity() -> None:
    assert (Money(Decimal("2.50")) * 3).amount == Decimal("7.50")


def test_currency_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="currency mismatch"):
        Money(Decimal("1"), "INR") + Money(Decimal("1"), "USD")


def test_invalid_currency_raises() -> None:
    with pytest.raises(ValueError, match="3-letter"):
        Money(Decimal("1"), "RUPEE")


def test_is_negative_and_zero() -> None:
    assert Money(Decimal("-1")).is_negative()
    assert Money.zero().amount == Decimal("0.00")


def test_frozen_value_object() -> None:
    m = Money(Decimal("1"))
    with pytest.raises(Exception):  # noqa: B017 - dataclass FrozenInstanceError
        m.amount = Decimal("2")  # type: ignore[misc]
