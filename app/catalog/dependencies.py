"""FastAPI wiring for the catalog service (repositories + object storage)."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.catalog.repository import (
    CategoryRepository,
    ProductImageRepository,
    ProductRepository,
)
from app.catalog.service import CatalogService
from app.common.storage import ObjectStorage
from app.db import get_session
from app.providers import get_object_storage


def get_catalog_service(
    session: Session = Depends(get_session),
    storage: ObjectStorage = Depends(get_object_storage),
) -> CatalogService:
    return CatalogService(
        session,
        CategoryRepository(session),
        ProductRepository(session),
        ProductImageRepository(session),
        storage,
    )
