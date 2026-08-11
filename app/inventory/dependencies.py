"""FastAPI wiring for the inventory service."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.catalog.repository import ProductRepository
from app.db import get_session
from app.inventory.repository import InventoryRepository, StockMovementRepository
from app.inventory.service import InventoryService


def get_inventory_service(
    session: Session = Depends(get_session),
) -> InventoryService:
    return InventoryService(
        session,
        InventoryRepository(session),
        StockMovementRepository(session),
        ProductRepository(session),
    )
