"""Payment API - thin controllers over PaymentService.

business_id and the actor come from the authenticated principal only. The client
never supplies amount, currency, business, provider result, or final status.
Mutations (initiate, verify, confirm-COD) require OWNER/EMPLOYEE; reads require any
authenticated principal. There is no generic "set payment status" endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, status

from app.auth.dependencies import Principal, get_current_principal, require_role
from app.common.security import Role
from app.payment.dependencies import get_payment_service
from app.payment.schemas import PaymentInitiate, PaymentOut, PaymentVerify
from app.payment.service import PaymentService

router = APIRouter(prefix="/api/payments", tags=["payments"])

_MUTATOR_ROLES = (Role.OWNER, Role.EMPLOYEE)


@router.post("", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def initiate_payment(
    payload: PaymentInitiate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentOut:
    payment, payment_url = service.initiate(
        principal.business_id,
        payload.order_id,
        payload.method,
        idempotency_key=idempotency_key,
    )
    return PaymentOut.from_model(payment, payment_url=payment_url)


@router.get("", response_model=list[PaymentOut])
def list_payments(
    principal: Principal = Depends(get_current_principal),
    service: PaymentService = Depends(get_payment_service),
) -> list[PaymentOut]:
    return [PaymentOut.from_model(p) for p in service.list_payments(principal.business_id)]


@router.get("/{payment_id}", response_model=PaymentOut)
def get_payment(
    payment_id: int,
    principal: Principal = Depends(get_current_principal),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentOut:
    return PaymentOut.from_model(service.get(principal.business_id, payment_id))


@router.post("/{payment_id}/verify", response_model=PaymentOut)
def verify_payment(
    payment_id: int,
    payload: PaymentVerify,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentOut:
    payment = service.verify(
        principal.business_id,
        payment_id,
        payload.provider_payment_id,
        actor_user_id=principal.user_id,
    )
    return PaymentOut.from_model(payment)


@router.post("/{payment_id}/confirm-cod", response_model=PaymentOut)
def confirm_cod(
    payment_id: int,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentOut:
    payment = service.confirm_cod(
        principal.business_id, payment_id, actor_user_id=principal.user_id
    )
    return PaymentOut.from_model(payment)
