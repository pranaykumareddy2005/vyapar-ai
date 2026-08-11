"""Catalog API - thin controllers over CatalogService.

Authorization uses the authenticated principal's ``business_id`` exclusively;
no endpoint accepts a client-supplied business id. Mutations require
OWNER/EMPLOYEE; product deletion additionally requires the Business PIN
(sensitive action, FR-AUTH-03).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.auth.dependencies import (
    Principal,
    get_current_principal,
    require_pin,
    require_role,
)
from app.catalog.dependencies import get_catalog_service
from app.catalog.schemas import (
    CategoryCreate,
    CategoryOut,
    ProductCreate,
    ProductImageOut,
    ProductOut,
    ProductUpdate,
)
from app.catalog.service import CatalogService
from app.common.security import Role

router = APIRouter(prefix="/api", tags=["catalog"])

_MUTATOR_ROLES = (Role.OWNER, Role.EMPLOYEE)


# --- categories -------------------------------------------------------------


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: CatalogService = Depends(get_catalog_service),
) -> CategoryOut:
    category = service.create_category(principal.business_id, payload.name)
    return CategoryOut.model_validate(category)


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(
    principal: Principal = Depends(get_current_principal),
    service: CatalogService = Depends(get_catalog_service),
) -> list[CategoryOut]:
    return [CategoryOut.model_validate(c) for c in service.list_categories(principal.business_id)]


# --- products ---------------------------------------------------------------


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: CatalogService = Depends(get_catalog_service),
) -> ProductOut:
    return ProductOut.from_model(service.create_product(principal.business_id, payload))


@router.get("/products", response_model=list[ProductOut])
def list_products(
    principal: Principal = Depends(get_current_principal),
    service: CatalogService = Depends(get_catalog_service),
    q: str | None = Query(default=None, max_length=100, description="keyword filter on name"),
    category_id: int | None = Query(default=None),
) -> list[ProductOut]:
    products = service.list_products(principal.business_id, keyword=q, category_id=category_id)
    return [ProductOut.from_model(p) for p in products]


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(
    product_id: int,
    principal: Principal = Depends(get_current_principal),
    service: CatalogService = Depends(get_catalog_service),
) -> ProductOut:
    return ProductOut.from_model(service.get_product(principal.business_id, product_id))


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: CatalogService = Depends(get_catalog_service),
) -> ProductOut:
    product = service.update_product(principal.business_id, product_id, payload)
    return ProductOut.from_model(product)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    # Sensitive action: OWNER/EMPLOYEE role AND Business PIN (FR-AUTH-03).
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    _pin: Principal = Depends(require_pin),
    service: CatalogService = Depends(get_catalog_service),
) -> None:
    service.soft_delete_product(principal.business_id, product_id)


# --- product images ---------------------------------------------------------


@router.post(
    "/products/{product_id}/images",
    response_model=ProductImageOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_product_image(
    product_id: int,
    file: UploadFile = File(...),
    is_primary: bool = Form(default=False),
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: CatalogService = Depends(get_catalog_service),
) -> ProductImageOut:
    data = await file.read()
    image = service.add_product_image(
        principal.business_id,
        product_id,
        data=data,
        content_type=file.content_type or "application/octet-stream",
        is_primary=is_primary,
    )
    return ProductImageOut.model_validate(image)


@router.get("/products/{product_id}/images", response_model=list[ProductImageOut])
def list_product_images(
    product_id: int,
    principal: Principal = Depends(get_current_principal),
    service: CatalogService = Depends(get_catalog_service),
) -> list[ProductImageOut]:
    images = service.list_product_images(principal.business_id, product_id)
    return [ProductImageOut.model_validate(i) for i in images]
