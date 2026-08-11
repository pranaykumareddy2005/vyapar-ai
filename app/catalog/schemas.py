"""Pydantic v2 schemas for the catalog API edge.

ORM models are never returned directly; every response uses an explicit schema.
Prices are represented as ``Decimal`` (validated positive, 2 dp) - never float.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.catalog.models import Product


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    name: str


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    sku: str = Field(min_length=1, max_length=64)
    category_id: int | None = None
    description: str | None = Field(default=None, max_length=5000)


class ProductUpdate(BaseModel):
    """Partial update; only provided fields change."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    category_id: int | None = None
    description: str | None = Field(default=None, max_length=5000)


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    category_id: int | None
    name: str
    description: str | None
    price: Decimal
    sku: str

    @classmethod
    def from_model(cls, product: Product) -> ProductOut:
        # Map the ORM ``price_amt`` column onto the API's ``price`` field.
        return cls(
            id=product.id,
            business_id=product.business_id,
            category_id=product.category_id,
            name=product.name,
            description=product.description,
            price=product.price_amt,
            sku=product.sku,
        )


class ProductImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    url: str
    content_type: str
    size_bytes: int | None
    is_primary: bool
