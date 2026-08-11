"""FastAPI wiring for the order service.

Shares one request-scoped ``Session`` with the inventory service so order
confirmation and its stock writes commit in a single transaction.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import Depends
from sqlalchemy.orm import Session

from app.catalog.repository import ProductRepository
from app.config import Settings, get_settings
from app.customer.repository import CustomerRepository
from app.db import get_session
from app.inventory.repository import InventoryRepository, StockMovementRepository
from app.inventory.service import InventoryService
from app.order.repository import OrderItemRepository, OrderRepository
from app.order.service import OrderService


def get_order_service(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OrderService:
    inventory = InventoryService(
        session,
        InventoryRepository(session),
        StockMovementRepository(session),
        ProductRepository(session),
    )
    return OrderService(
        session,
        OrderRepository(session),
        OrderItemRepository(session),
        CustomerRepository(session),
        ProductRepository(session),
        inventory,
        tax_rate=Decimal(str(settings.default_tax_rate)),
    )
