"""Pydantic schemas for the order API edge.

Clients submit only ``customer_id`` and line items (product + quantity). Prices
and totals are NEVER accepted from the client - the server snapshots the price
from the catalog and computes all totals (plan items 10, 11).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from app.order.models import OrderEvent

if TYPE_CHECKING:
    from app.order.models import Order, OrderItem


class OrderItemIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0, le=1_000_000)


class OrderCreate(BaseModel):
    customer_id: int
    items: list[OrderItemIn] = Field(min_length=1)


class OrderTransitionRequest(BaseModel):
    event: OrderEvent


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: str
    unit_price: Decimal
    quantity: int
    line_total: Decimal

    @classmethod
    def from_model(cls, item: OrderItem) -> OrderItemOut:
        return cls(
            id=item.id,
            product_id=item.product_id,
            product_name=item.product_name,
            unit_price=item.unit_price,
            quantity=item.quantity,
            line_total=item.line_total(),
        )


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    customer_id: int
    status: str
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    items: list[OrderItemOut]

    @classmethod
    def from_model(cls, order: Order) -> OrderOut:
        items = [OrderItemOut.from_model(i) for i in order.items]
        subtotal = order.total_amt - order.tax_amt
        return cls(
            id=order.id,
            business_id=order.business_id,
            customer_id=order.customer_id,
            status=order.status.value,
            subtotal=subtotal,
            tax=order.tax_amt,
            total=order.total_amt,
            items=items,
        )
