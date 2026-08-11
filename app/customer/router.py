"""Customer API - thin controllers over CustomerService.

business_id comes from the authenticated principal only. Mutations require
OWNER/EMPLOYEE; reads require any authenticated principal.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.auth.dependencies import Principal, get_current_principal, require_role
from app.common.security import Role
from app.customer.dependencies import get_customer_service
from app.customer.schemas import (
    AddressCreate,
    AddressOut,
    CustomerCreate,
    CustomerOut,
    CustomerUpdate,
)
from app.customer.service import CustomerService

router = APIRouter(prefix="/api/customers", tags=["customers"])

_MUTATOR_ROLES = (Role.OWNER, Role.EMPLOYEE)


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: CustomerService = Depends(get_customer_service),
) -> CustomerOut:
    customer = service.create(principal.business_id, payload.name, payload.phone)
    return CustomerOut.model_validate(customer)


@router.get("", response_model=list[CustomerOut])
def list_customers(
    principal: Principal = Depends(get_current_principal),
    service: CustomerService = Depends(get_customer_service),
) -> list[CustomerOut]:
    return [CustomerOut.model_validate(c) for c in service.list_customers(principal.business_id)]


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: int,
    principal: Principal = Depends(get_current_principal),
    service: CustomerService = Depends(get_customer_service),
) -> CustomerOut:
    return CustomerOut.model_validate(service.get(principal.business_id, customer_id))


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: CustomerService = Depends(get_customer_service),
) -> CustomerOut:
    return CustomerOut.model_validate(service.update(principal.business_id, customer_id, payload))


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    customer_id: int,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: CustomerService = Depends(get_customer_service),
) -> None:
    service.soft_delete(principal.business_id, customer_id)


@router.post(
    "/{customer_id}/addresses", response_model=AddressOut, status_code=status.HTTP_201_CREATED
)
def add_address(
    customer_id: int,
    payload: AddressCreate,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: CustomerService = Depends(get_customer_service),
) -> AddressOut:
    address = service.add_address(
        principal.business_id, customer_id, line=payload.line, city=payload.city, pin=payload.pin
    )
    return AddressOut.model_validate(address)


@router.get("/{customer_id}/addresses", response_model=list[AddressOut])
def list_addresses(
    customer_id: int,
    principal: Principal = Depends(get_current_principal),
    service: CustomerService = Depends(get_customer_service),
) -> list[AddressOut]:
    addresses = service.list_addresses(principal.business_id, customer_id)
    return [AddressOut.model_validate(a) for a in addresses]
