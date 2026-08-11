"""FastAPI wiring for the customer service."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.customer.repository import CustomerAddressRepository, CustomerRepository
from app.customer.service import CustomerService
from app.db import get_session


def get_customer_service(session: Session = Depends(get_session)) -> CustomerService:
    return CustomerService(
        session,
        CustomerRepository(session),
        CustomerAddressRepository(session),
    )
