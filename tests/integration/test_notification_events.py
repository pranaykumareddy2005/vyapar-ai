"""Integration tests: domain event -> notification via the real listener.

Real committed PostgreSQL data + the NotificationEventListener wired to a local
EventBus (independent SessionLocal writes). Verifies the event pipeline and the
dedup invariant, then cleans up.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.business.models import Business
from app.common.events import EventBus, LowStock, PaymentSucceeded
from app.db import SessionLocal
from app.notification.listener import NotificationEventListener
from app.notification.models import Notification
from sqlalchemy import delete, func, select


@contextmanager
def _business() -> Iterator[int]:
    session = SessionLocal()
    try:
        biz = Business(
            name="NotifBiz", category="grocery", contact_number="+910000000000", address="a"
        )
        session.add(biz)
        session.commit()
        biz_id = biz.id
    finally:
        session.close()
    try:
        yield biz_id
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.execute(delete(Business).where(Business.id == biz_id))  # cascades notification
            cleanup.commit()
        finally:
            cleanup.close()


def _notifications_for(business_id: int) -> list[Notification]:
    session = SessionLocal()
    try:
        return list(
            session.scalars(select(Notification).where(Notification.business_id == business_id))
        )
    finally:
        session.close()


def _count(business_id: int) -> int:
    session = SessionLocal()
    try:
        return session.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.business_id == business_id)
        ).scalar_one()
    finally:
        session.close()


def _bus() -> EventBus:
    bus = EventBus()
    NotificationEventListener(SessionLocal).register(bus)
    return bus


def test_low_stock_event_creates_notification() -> None:
    with _business() as biz_id:
        bus = _bus()
        bus.publish(LowStock(business_id=biz_id, product_id=7, quantity=2, threshold=5))
        notes = _notifications_for(biz_id)
        assert len(notes) == 1
        assert notes[0].type.value == "LOW_STOCK"
        assert notes[0].related_entity_id == 7


def test_payment_event_creates_notification() -> None:
    with _business() as biz_id:
        bus = _bus()
        bus.publish(PaymentSucceeded(business_id=biz_id, order_id=4, payment_id=11))
        notes = _notifications_for(biz_id)
        assert len(notes) == 1
        assert notes[0].type.value == "PAYMENT_SUCCESS"


def test_duplicate_event_is_deduplicated() -> None:
    with _business() as biz_id:
        bus = _bus()
        event = LowStock(business_id=biz_id, product_id=7, quantity=2, threshold=5)
        bus.publish(event)
        bus.publish(event)  # same dedup_key -> absorbed
        assert _count(biz_id) == 1
