"""Business API - thin controllers over BusinessService.

All routes operate on the caller's OWN business (``principal.business_id``);
there is no business id in any path, so cross-tenant access by id manipulation
is structurally impossible here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.auth.dependencies import (
    Principal,
    get_business_service,
    get_current_principal,
    require_pin,
    require_role,
)
from app.business.schemas import (
    BusinessOut,
    BusinessUpdate,
    PaymentPreferenceUpdate,
    PinSetRequest,
    WhatsappLinkRequest,
)
from app.business.service import BusinessService
from app.common.security import Role

router = APIRouter(prefix="/api/business", tags=["business"])


@router.get("/me", response_model=BusinessOut)
def get_my_business(
    principal: Principal = Depends(get_current_principal),
    service: BusinessService = Depends(get_business_service),
) -> BusinessOut:
    return BusinessOut.from_model(service.get(principal.business_id))


@router.patch("/me", response_model=BusinessOut)
def update_my_business(
    payload: BusinessUpdate,
    principal: Principal = Depends(require_role(Role.OWNER)),
    service: BusinessService = Depends(get_business_service),
) -> BusinessOut:
    return BusinessOut.from_model(service.update_profile(principal.business_id, payload))


@router.put("/me/whatsapp", response_model=BusinessOut)
def link_whatsapp(
    payload: WhatsappLinkRequest,
    principal: Principal = Depends(require_role(Role.OWNER)),
    service: BusinessService = Depends(get_business_service),
) -> BusinessOut:
    return BusinessOut.from_model(
        service.link_whatsapp(principal.business_id, payload.whatsapp_number)
    )


@router.post("/me/pin", status_code=status.HTTP_204_NO_CONTENT)
def set_pin(
    payload: PinSetRequest,
    principal: Principal = Depends(require_role(Role.OWNER)),
    service: BusinessService = Depends(get_business_service),
) -> None:
    service.set_pin(principal.business_id, payload.pin)


@router.put("/me/payment-preferences", response_model=BusinessOut)
def update_payment_preferences(
    payload: PaymentPreferenceUpdate,
    # Sensitive action ("change payout settings") - OWNER role AND Business PIN.
    principal: Principal = Depends(require_role(Role.OWNER)),
    _pin: Principal = Depends(require_pin),
    service: BusinessService = Depends(get_business_service),
) -> BusinessOut:
    return BusinessOut.from_model(
        service.update_payment_preference(principal.business_id, payload.payment_preference)
    )
