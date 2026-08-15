"""Customer persistence. Tenant-scoped by ``business_id``; persistence-only."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer.models import Customer, CustomerAddress


class CustomerRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, customer: Customer) -> Customer:
        self._session.add(customer)
        self._session.flush()
        return customer

    def get(
        self, business_id: int, customer_id: int, *, include_deleted: bool = False
    ) -> Customer | None:
        stmt = select(Customer).where(
            Customer.id == customer_id, Customer.business_id == business_id
        )
        if not include_deleted:
            stmt = stmt.where(Customer.is_deleted.is_(False))
        return self._session.scalars(stmt).one_or_none()

    def list(self, business_id: int) -> list[Customer]:
        stmt = (
            select(Customer)
            .where(Customer.business_id == business_id, Customer.is_deleted.is_(False))
            .order_by(Customer.id)
        )
        return list(self._session.scalars(stmt).all())

    def get_active_by_phone(self, business_id: int, phone: str) -> Customer | None:
        stmt = select(Customer).where(
            Customer.business_id == business_id,
            Customer.phone == phone,
            Customer.is_deleted.is_(False),
        )
        return self._session.scalars(stmt).one_or_none()

    def active_phone_exists(
        self, business_id: int, phone: str, *, exclude_customer_id: int | None = None
    ) -> bool:
        stmt = select(Customer.id).where(
            Customer.business_id == business_id,
            Customer.phone == phone,
            Customer.is_deleted.is_(False),
        )
        if exclude_customer_id is not None:
            stmt = stmt.where(Customer.id != exclude_customer_id)
        return self._session.scalars(stmt).first() is not None


class CustomerAddressRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, address: CustomerAddress) -> CustomerAddress:
        self._session.add(address)
        self._session.flush()
        return address

    def list_for_customer(self, business_id: int, customer_id: int) -> list[CustomerAddress]:
        stmt = (
            select(CustomerAddress)
            .where(
                CustomerAddress.business_id == business_id,
                CustomerAddress.customer_id == customer_id,
            )
            .order_by(CustomerAddress.id)
        )
        return list(self._session.scalars(stmt).all())
