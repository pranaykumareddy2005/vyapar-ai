"""Customer application service - the clean boundary Order and future modules use.

All methods are tenant-scoped by an explicit ``business_id`` from the authenticated
principal. Customers are soft-deleted so historical orders remain valid.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.exceptions import ConflictError, NotFoundError
from app.customer.models import Customer, CustomerAddress
from app.customer.repository import CustomerAddressRepository, CustomerRepository
from app.customer.schemas import CustomerUpdate


class CustomerService:
    def __init__(
        self,
        session: Session,
        customers: CustomerRepository,
        addresses: CustomerAddressRepository,
    ) -> None:
        self._session = session
        self._customers = customers
        self._addresses = addresses

    def create(self, business_id: int, name: str, phone: str) -> Customer:
        if self._customers.active_phone_exists(business_id, phone):
            raise ConflictError("a customer with this phone already exists")
        try:
            customer = self._customers.add(
                Customer(business_id=business_id, name=name, phone=phone)
            )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("a customer with this phone already exists") from exc
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(customer)
        return customer

    def get(self, business_id: int, customer_id: int) -> Customer:
        customer = self._customers.get(business_id, customer_id)
        if customer is None:
            raise NotFoundError("customer not found")
        return customer

    def list_customers(self, business_id: int) -> list[Customer]:
        return self._customers.list(business_id)

    def update(self, business_id: int, customer_id: int, payload: CustomerUpdate) -> Customer:
        customer = self.get(business_id, customer_id)
        data = payload.model_dump(exclude_unset=True)
        if "phone" in data and self._customers.active_phone_exists(
            business_id, data["phone"], exclude_customer_id=customer_id
        ):
            raise ConflictError("a customer with this phone already exists")
        try:
            if "name" in data:
                customer.name = data["name"]
            if "phone" in data:
                customer.phone = data["phone"]
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("a customer with this phone already exists") from exc
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(customer)
        return customer

    def soft_delete(self, business_id: int, customer_id: int) -> None:
        customer = self.get(business_id, customer_id)
        try:
            customer.is_deleted = True
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    # --- addresses --------------------------------------------------------

    def add_address(
        self, business_id: int, customer_id: int, *, line: str, city: str, pin: str
    ) -> CustomerAddress:
        self.get(business_id, customer_id)  # ownership check
        try:
            address = self._addresses.add(
                CustomerAddress(
                    business_id=business_id,
                    customer_id=customer_id,
                    line=line,
                    city=city,
                    pin=pin,
                )
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(address)
        return address

    def list_addresses(self, business_id: int, customer_id: int) -> list[CustomerAddress]:
        self.get(business_id, customer_id)
        return self._addresses.list_for_customer(business_id, customer_id)
