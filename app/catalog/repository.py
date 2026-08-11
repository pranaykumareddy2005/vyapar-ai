"""Catalog data access. Every query is tenant-scoped by ``business_id``.

Repositories are responsible for persistence only - no business rules here.
Soft-deleted products are excluded unless ``include_deleted`` is set (used by
internal callers, never exposed as a normal listing).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import Category, Product, ProductImage


class CategoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, category: Category) -> Category:
        self._session.add(category)
        self._session.flush()
        return category

    def get(self, business_id: int, category_id: int) -> Category | None:
        stmt = select(Category).where(
            Category.id == category_id, Category.business_id == business_id
        )
        return self._session.scalars(stmt).one_or_none()

    def list(self, business_id: int) -> list[Category]:
        stmt = select(Category).where(Category.business_id == business_id).order_by(Category.name)
        return list(self._session.scalars(stmt).all())

    def exists_by_name(self, business_id: int, name: str) -> bool:
        stmt = select(Category.id).where(Category.business_id == business_id, Category.name == name)
        return self._session.scalars(stmt).first() is not None


class ProductRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, product: Product) -> Product:
        self._session.add(product)
        self._session.flush()
        return product

    def get(
        self, business_id: int, product_id: int, *, include_deleted: bool = False
    ) -> Product | None:
        stmt = select(Product).where(Product.id == product_id, Product.business_id == business_id)
        if not include_deleted:
            stmt = stmt.where(Product.is_deleted.is_(False))
        return self._session.scalars(stmt).one_or_none()

    def list(
        self,
        business_id: int,
        *,
        keyword: str | None = None,
        category_id: int | None = None,
    ) -> list[Product]:
        stmt = select(Product).where(
            Product.business_id == business_id,
            Product.is_deleted.is_(False),
        )
        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(Product.name.ilike(like))
        stmt = stmt.order_by(Product.id)
        return list(self._session.scalars(stmt).all())

    def active_sku_exists(
        self, business_id: int, sku: str, *, exclude_product_id: int | None = None
    ) -> bool:
        stmt = select(Product.id).where(
            Product.business_id == business_id,
            Product.sku == sku,
            Product.is_deleted.is_(False),
        )
        if exclude_product_id is not None:
            stmt = stmt.where(Product.id != exclude_product_id)
        return self._session.scalars(stmt).first() is not None


class ProductImageRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, image: ProductImage) -> ProductImage:
        self._session.add(image)
        self._session.flush()
        return image

    def list_for_product(self, business_id: int, product_id: int) -> list[ProductImage]:
        stmt = (
            select(ProductImage)
            .where(
                ProductImage.business_id == business_id,
                ProductImage.product_id == product_id,
            )
            .order_by(ProductImage.id)
        )
        return list(self._session.scalars(stmt).all())
