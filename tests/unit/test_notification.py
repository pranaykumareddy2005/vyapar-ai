"""Unit tests: event -> notification mapping (deterministic, no I/O)."""

from __future__ import annotations

from app.common.events import (
    LowStock,
    OrderCancelled,
    OrderConfirmed,
    OrderCreated,
    PaymentFailed,
    PaymentSucceeded,
)
from app.notification import messages
from app.notification.models import NotificationType


def test_low_stock_mapping() -> None:
    draft = messages.from_low_stock(LowStock(business_id=1, product_id=7, quantity=2, threshold=5))
    assert draft.business_id == 1
    assert draft.type is NotificationType.LOW_STOCK
    assert draft.related_entity_type == "product"
    assert draft.related_entity_id == 7
    assert draft.dedup_key == "LOW_STOCK:7"
    assert "2 left" in draft.body and "threshold 5" in draft.body


def test_order_event_mappings() -> None:
    created = messages.from_order_created(OrderCreated(business_id=1, order_id=9, customer_id=3))
    confirmed = messages.from_order_confirmed(
        OrderConfirmed(business_id=1, order_id=9, customer_id=3)
    )
    cancelled = messages.from_order_cancelled(
        OrderCancelled(business_id=1, order_id=9, customer_id=3)
    )
    assert created.type is NotificationType.ORDER_CREATED
    assert created.dedup_key == "ORDER_CREATED:9"
    assert confirmed.type is NotificationType.ORDER_CONFIRMED
    assert confirmed.dedup_key == "ORDER_CONFIRMED:9"
    assert cancelled.type is NotificationType.ORDER_CANCELLED
    assert cancelled.dedup_key == "ORDER_CANCELLED:9"
    for d in (created, confirmed, cancelled):
        assert d.related_entity_type == "order"
        assert d.related_entity_id == 9


def test_payment_event_mappings() -> None:
    ok = messages.from_payment_succeeded(PaymentSucceeded(business_id=2, order_id=4, payment_id=11))
    failed = messages.from_payment_failed(
        PaymentFailed(business_id=2, order_id=4, payment_id=12, failure_code="amount_mismatch")
    )
    assert ok.type is NotificationType.PAYMENT_SUCCESS
    assert ok.dedup_key == "PAYMENT_SUCCESS:11"
    assert ok.related_entity_id == 11
    assert failed.type is NotificationType.PAYMENT_FAILED
    assert failed.dedup_key == "PAYMENT_FAILED:12"
    assert "amount_mismatch" in failed.body
