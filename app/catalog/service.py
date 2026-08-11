"""Catalog application service - the clean boundary other modules use.

The future AI Catalog Generator will call :meth:`CatalogService.create_product`
after merchant approval; it must not reach into repositories directly. All
methods are tenant-scoped by an explicit ``business_id`` taken from the
authenticated principal (never from client-supplied data).
"""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalog.models import Category, Product, ProductImage
from app.catalog.repository import (
    CategoryRepository,
    ProductImageRepository,
    ProductRepository,
)
from app.catalog.schemas import ProductCreate, ProductUpdate
from app.common.exceptions import ConflictError, NotFoundError, ValidationError
from app.common.storage import ObjectStorage

_ALLOWED_IMAGE_PREFIX = "image/"


class CatalogService:
    def __init__(
        self,
        session: Session,
        categories: CategoryRepository,
        products: ProductRepository,
        images: ProductImageRepository,
        storage: ObjectStorage,
    ) -> None:
        self._session = session
        self._categories = categories
        self._products = products
        self._images = images
        self._storage = storage

    # --- categories -------------------------------------------------------

    def create_category(self, business_id: int, name: str) -> Category:
        if self._categories.exists_by_name(business_id, name):
            raise ConflictError("category name already exists")
        try:
            category = self._categories.add(Category(business_id=business_id, name=name))
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("category name already exists") from exc
        except Exception:
            self._session.rollback()
            raise
        return category

    def list_categories(self, business_id: int) -> list[Category]:
        return self._categories.list(business_id)

    def get_category(self, business_id: int, category_id: int) -> Category:
        category = self._categories.get(business_id, category_id)
        if category is None:
            raise NotFoundError("category not found")
        return category

    def _validate_category_ownership(self, business_id: int, category_id: int | None) -> None:
        if category_id is not None and self._categories.get(business_id, category_id) is None:
            # Includes categories that belong to another business (tenant-safe).
            raise ValidationError("category does not exist for this business")

    # --- products ---------------------------------------------------------

    def create_product(self, business_id: int, payload: ProductCreate) -> Product:
        self._validate_category_ownership(business_id, payload.category_id)
        if self._products.active_sku_exists(business_id, payload.sku):
            raise ConflictError("sku already exists for this business")
        try:
            product = self._products.add(
                Product(
                    business_id=business_id,
                    category_id=payload.category_id,
                    name=payload.name,
                    description=payload.description,
                    price_amt=payload.price,
                    sku=payload.sku,
                )
            )
            self._session.commit()
        except IntegrityError as exc:
            # Backstop for a concurrent insert racing the SKU check.
            self._session.rollback()
            raise ConflictError("sku already exists for this business") from exc
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(product)
        return product

    def get_product(self, business_id: int, product_id: int) -> Product:
        product = self._products.get(business_id, product_id)
        if product is None:
            raise NotFoundError("product not found")
        return product

    def list_products(
        self,
        business_id: int,
        *,
        keyword: str | None = None,
        category_id: int | None = None,
    ) -> list[Product]:
        return self._products.list(business_id, keyword=keyword, category_id=category_id)

    def update_product(self, business_id: int, product_id: int, payload: ProductUpdate) -> Product:
        product = self.get_product(business_id, product_id)
        data = payload.model_dump(exclude_unset=True)

        if "category_id" in data:
            self._validate_category_ownership(business_id, data["category_id"])
        if "sku" in data and self._products.active_sku_exists(
            business_id, data["sku"], exclude_product_id=product_id
        ):
            raise ConflictError("sku already exists for this business")

        try:
            if "name" in data:
                product.name = data["name"]
            if "description" in data:
                product.description = data["description"]
            if "sku" in data:
                product.sku = data["sku"]
            if "category_id" in data:
                product.category_id = data["category_id"]
            if "price" in data:
                product.price_amt = data["price"]
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("sku already exists for this business") from exc
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(product)
        return product

    def soft_delete_product(self, business_id: int, product_id: int) -> None:
        product = self.get_product(business_id, product_id)
        try:
            product.is_deleted = True
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    # --- images -----------------------------------------------------------

    def add_product_image(
        self,
        business_id: int,
        product_id: int,
        *,
        data: bytes,
        content_type: str,
        is_primary: bool = False,
    ) -> ProductImage:
        # Ownership check ensures cross-tenant product ids cannot be targeted.
        self.get_product(business_id, product_id)
        if not content_type.startswith(_ALLOWED_IMAGE_PREFIX):
            raise ValidationError("only image content types are supported")
        if not data:
            raise ValidationError("empty image payload")

        key = f"{business_id}/products/{product_id}/{uuid.uuid4().hex}"
        url = self._storage.put(key, data, content_type)
        try:
            image = self._images.add(
                ProductImage(
                    product_id=product_id,
                    business_id=business_id,
                    storage_key=key,
                    url=url,
                    content_type=content_type,
                    size_bytes=len(data),
                    is_primary=is_primary,
                )
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(image)
        return image

    def list_product_images(self, business_id: int, product_id: int) -> list[ProductImage]:
        self.get_product(business_id, product_id)
        return self._images.list_for_product(business_id, product_id)
