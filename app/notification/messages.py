"""Deterministic event -> notification mapping.

Pure functions (no I/O) that turn a domain event into the notification fields.
Kept separate so the mapping is unit-testable without a database. Messages carry
only minimal business information - no secrets, no unnecessary PII.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.common.events import (
    LowStock,
    OrderCancelled,
    OrderConfirmed,
    OrderCreated,
    PaymentFailed,
    PaymentSucceeded,
)
from app.notification.models import NotificationType


@dataclass(frozen=True, slots=True)
class NotificationDraft:
    business_id: int
    type: NotificationType
    title: str
    body: str
    related_entity_type: str | None
    related_entity_id: int | None
    dedup_key: str


def from_low_stock(event: LowStock) -> NotificationDraft:
    return NotificationDraft(
        business_id=event.business_id,
        type=NotificationType.LOW_STOCK,
        title="Low stock",
        body=(
            f"Product #{event.product_id} is low: {event.quantity} left "
            f"(threshold {event.threshold})."
        ),
        related_entity_type="product",
        related_entity_id=event.product_id,
        # One low-stock notification per product (documented MVP dedup).
        dedup_key=f"LOW_STOCK:{event.product_id}",
    )


def from_order_created(event: OrderCreated) -> NotificationDraft:
    return NotificationDraft(
        business_id=event.business_id,
        type=NotificationType.ORDER_CREATED,
        title="Order created",
        body=f"Order #{event.order_id} was created.",
        related_entity_type="order",
        related_entity_id=event.order_id,
        dedup_key=f"ORDER_CREATED:{event.order_id}",
    )


def from_order_confirmed(event: OrderConfirmed) -> NotificationDraft:
    return NotificationDraft(
        business_id=event.business_id,
        type=NotificationType.ORDER_CONFIRMED,
        title="Order confirmed",
        body=f"Order #{event.order_id} was confirmed.",
        related_entity_type="order",
        related_entity_id=event.order_id,
        dedup_key=f"ORDER_CONFIRMED:{event.order_id}",
    )


def from_order_cancelled(event: OrderCancelled) -> NotificationDraft:
    return NotificationDraft(
        business_id=event.business_id,
        type=NotificationType.ORDER_CANCELLED,
        title="Order cancelled",
        body=f"Order #{event.order_id} was cancelled.",
        related_entity_type="order",
        related_entity_id=event.order_id,
        dedup_key=f"ORDER_CANCELLED:{event.order_id}",
    )


def from_payment_succeeded(event: PaymentSucceeded) -> NotificationDraft:
    return NotificationDraft(
        business_id=event.business_id,
        type=NotificationType.PAYMENT_SUCCESS,
        title="Payment received",
        body=f"Payment for order #{event.order_id} succeeded.",
        related_entity_type="payment",
        related_entity_id=event.payment_id,
        dedup_key=f"PAYMENT_SUCCESS:{event.payment_id}",
    )


def from_payment_failed(event: PaymentFailed) -> NotificationDraft:
    return NotificationDraft(
        business_id=event.business_id,
        type=NotificationType.PAYMENT_FAILED,
        title="Payment failed",
        body=f"Payment for order #{event.order_id} failed ({event.failure_code}).",
        related_entity_type="payment",
        related_entity_id=event.payment_id,
        dedup_key=f"PAYMENT_FAILED:{event.payment_id}",
    )
