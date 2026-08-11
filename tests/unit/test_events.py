from __future__ import annotations

from app.common.events import DomainEvent, EventBus, LowStock


def test_publish_invokes_subscriber() -> None:
    bus = EventBus()
    received: list[LowStock] = []
    bus.subscribe(LowStock, received.append)

    event = LowStock(business_id=1, product_id=2, quantity=1, threshold=5)
    bus.publish(event)

    assert received == [event]


def test_only_matching_type_delivered() -> None:
    bus = EventBus()
    calls: list[DomainEvent] = []
    bus.subscribe(LowStock, calls.append)
    bus.publish(DomainEvent())  # unrelated event type
    assert calls == []


def test_handler_exception_is_isolated() -> None:
    bus = EventBus()
    seen: list[int] = []

    def boom(_: LowStock) -> None:
        raise RuntimeError("handler failure")

    bus.subscribe(LowStock, boom)
    bus.subscribe(LowStock, lambda e: seen.append(e.product_id))

    bus.publish(LowStock(business_id=1, product_id=9, quantity=0, threshold=1))
    assert seen == [9]  # sibling handler still ran
