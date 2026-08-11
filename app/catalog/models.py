"""Catalog ORM models: Category, Product, ProductImage.

All three are tenant-scoped by ``business_id``. Product uses soft deletion
(``is_deleted``); SKU is unique per business among *active* (non-deleted)
products, so a deleted product's SKU may be reused. Product state is kept
strictly separate from stock state (no quantity columns here).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db_mixins import TimestampMixin
from app.common.money import Money
from app.db import Base


class Category(TimestampMixin, Base):
    __tablename__ = "category"
    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_category_business_name"),
        Index("ix_category_business_id", "business_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class Product(TimestampMixin, Base):
    __tablename__ = "product"
    __table_args__ = (
        # SKU unique per business among active products only; a soft-deleted
        # product's SKU can be reclaimed (documented Phase-3 decision).
        Index(
            "uq_product_business_sku_active",
            "business_id",
            "sku",
            unique=True,
            postgresql_where="is_deleted = false",
        ),
        # Supports business-scoped listing and category filtering.
        Index("ix_product_business_category", "business_id", "category_id"),
        Index("ix_product_business_active", "business_id", "is_deleted"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable per LLD; when set, ownership is validated in the service.
    category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("category.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Populated by the merchant now, and by the AI Catalog Generator later.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_amt: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    images: Mapped[list[ProductImage]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.id",
    )

    def price(self) -> Money:
        """Return the price as a Money value object (no float arithmetic)."""
        return Money(self.price_amt)


class ProductImage(TimestampMixin, Base):
    __tablename__ = "product_image"
    __table_args__ = (
        Index("ix_product_image_product_id", "product_id"),
        Index("ix_product_image_business_id", "business_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("product.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized tenant key so image queries stay tenant-scoped without a join.
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    product: Mapped[Product] = relationship(back_populates="images")
