"""Inventory API - thin controllers over InventoryService.

Authorization uses the authenticated principal's ``business_id`` exclusively.
Mutations (create inventory, adjust stock, update threshold) require
OWNER/EMPLOYEE; reads require any authenticated principal. Stock adjustment is
not a FR-AUTH-03 destructive action, so it is not PIN-gated
(see docs/history/phase5_schema_decision.md D10). No stock math lives in handlers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.auth.dependencies import Principal, get_current_principal, require_role
from app.common.security import Role
from app.inventory.dependencies import get_inventory_service
from app.inventory.schemas import (
    InventoryCreate,
    InventoryOut,
    StockAdjust,
    StockMovementOut,
    ThresholdUpdate,
)
from app.inventory.service import InventoryService

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

_MUTATOR_ROLES = (Role.OWNER, Role.EMPLOYEE)


@router.post("", response_model=InventoryOut, status_code=status.HTTP_201_CREATED)
def create_inventory(
    payload: InventoryCreate,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryOut:
    inventory = service.create_inventory(
        principal.business_id,
        payload.product_id,
        quantity=payload.quantity,
        low_stock_threshold=payload.low_stock_threshold,
    )
    return InventoryOut.from_model(inventory)


@router.get("", response_model=list[InventoryOut])
def list_inventory(
    principal: Principal = Depends(get_current_principal),
    service: InventoryService = Depends(get_inventory_service),
) -> list[InventoryOut]:
    return [InventoryOut.from_model(i) for i in service.list_inventory(principal.business_id)]


@router.get("/{inventory_id}", response_model=InventoryOut)
def get_inventory(
    inventory_id: int,
    principal: Principal = Depends(get_current_principal),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryOut:
    return InventoryOut.from_model(service.get_inventory(principal.business_id, inventory_id))


@router.patch("/{inventory_id}", response_model=InventoryOut)
def update_threshold(
    inventory_id: int,
    payload: ThresholdUpdate,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryOut:
    inventory = service.update_threshold(
        principal.business_id, inventory_id, payload.low_stock_threshold
    )
    return InventoryOut.from_model(inventory)


@router.post("/{inventory_id}/adjust", response_model=InventoryOut)
def adjust_stock(
    inventory_id: int,
    payload: StockAdjust,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryOut:
    inventory = service.adjust_stock(
        principal.business_id,
        inventory_id,
        delta=payload.delta,
        movement_type=payload.movement_type,
        actor_user_id=principal.user_id,
    )
    return InventoryOut.from_model(inventory)


@router.get("/{inventory_id}/movements", response_model=list[StockMovementOut])
def list_movements(
    inventory_id: int,
    principal: Principal = Depends(get_current_principal),
    service: InventoryService = Depends(get_inventory_service),
) -> list[StockMovementOut]:
    movements = service.list_movements(principal.business_id, inventory_id)
    return [StockMovementOut.model_validate(m) for m in movements]
