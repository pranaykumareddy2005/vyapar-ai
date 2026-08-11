from __future__ import annotations

from decimal import Decimal

import pytest
from app.catalog.schemas import ProductCreate, ProductUpdate
from pydantic import ValidationError


def test_valid_product_create() -> None:
    p = ProductCreate(name="Notebook", price=Decimal("120.50"), sku="NB-1")
    assert p.price == Decimal("120.50")
    assert p.category_id is None


def test_negative_price_rejected() -> None:
    with pytest.raises(ValidationError):
        ProductCreate(name="X", price=Decimal("-1"), sku="S1")


def test_zero_price_rejected() -> None:
    with pytest.raises(ValidationError):
        ProductCreate(name="X", price=Decimal("0"), sku="S1")


def test_too_many_decimals_rejected() -> None:
    with pytest.raises(ValidationError):
        ProductCreate(name="X", price=Decimal("1.234"), sku="S1")


def test_missing_required_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        ProductCreate(name="X")  # type: ignore[call-arg]


def test_empty_sku_rejected() -> None:
    with pytest.raises(ValidationError):
        ProductCreate(name="X", price=Decimal("1.00"), sku="")


def test_update_is_all_optional() -> None:
    u = ProductUpdate()
    assert u.model_dump(exclude_unset=True) == {}
