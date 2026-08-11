"""Order API - thin controllers over OrderService.

business_id and the stock-movement actor come from the authenticated principal.
Mutations (create, transition) require OWNER/EMPLOYEE; reads require any
authenticated principal. There is no raw status write - lifecycle changes go
through the guarded transition endpoint only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.auth.dependencies import Principal, get_current_principal, require_role
from app.common.exceptions import ConflictError
from app.common.security import Role
from app.order.dependencies import get_order_service
from app.order.models import OrderEvent
from app.order.schemas import OrderCreate, OrderOut, OrderTransitionRequest
from app.order.service import OrderService

router = APIRouter(prefix="/api/orders", tags=["orders"])

_MUTATOR_ROLES = (Role.OWNER, Role.EMPLOYEE)


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: OrderService = Depends(get_order_service),
) -> OrderOut:
    return OrderOut.from_model(service.create_order(principal.business_id, payload))


@router.get("", response_model=list[OrderOut])
def list_orders(
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
) -> list[OrderOut]:
    return [OrderOut.from_model(o) for o in service.list_orders(principal.business_id)]


@router.get("/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
) -> OrderOut:
    return OrderOut.from_model(service.get_order(principal.business_id, order_id))


@router.post("/{order_id}/transition", response_model=OrderOut)
def transition_order(
    order_id: int,
    payload: OrderTransitionRequest,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: OrderService = Depends(get_order_service),
) -> OrderOut:
    # Phase 8: reaching PAID must go through verified payment (PaymentService),
    # not a raw client transition. The PAY transition remains available to
    # PaymentService via the OrderService boundary; only client HTTP access is
    # blocked here (docs/phase8_schema_decision.md D6).
    if payload.event is OrderEvent.PAY:
        raise ConflictError("use the payment API to mark an order paid")
    order = service.transition(
        principal.business_id, order_id, payload.event, actor_user_id=principal.user_id
    )
    return OrderOut.from_model(order)
