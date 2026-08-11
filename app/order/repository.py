"""Order persistence. Tenant-scoped by ``business_id``; persistence-only."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.order.models import Order, OrderItem


class OrderRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, order: Order) -> Order:
        self._session.add(order)
        self._session.flush()
        return order

    def get(self, business_id: int, order_id: int) -> Order | None:
        stmt = select(Order).where(Order.id == order_id, Order.business_id == business_id)
        return self._session.scalars(stmt).one_or_none()

    def list(self, business_id: int) -> list[Order]:
        stmt = select(Order).where(Order.business_id == business_id).order_by(Order.id.desc())
        return list(self._session.scalars(stmt).all())


class OrderItemRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, item: OrderItem) -> OrderItem:
        self._session.add(item)
        self._session.flush()
        return item
