"""In-process domain event foundation.

A lightweight synchronous publish/subscribe bus. Domain services publish events
(e.g. ``LowStock``) without knowing who consumes them; the notification module
subscribes in later phases. This keeps modules decoupled (Observer pattern)
while staying inside the single monolith process.

The bus is intentionally simple and synchronous for the MVP. Handlers are
invoked in registration order; a failing handler is isolated so it cannot
break the publisher or sibling handlers.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Base class for all domain events."""


@dataclass(frozen=True, slots=True)
class LowStock(DomainEvent):
    """Published when a product's stock falls to or below its threshold."""

    business_id: int
    product_id: int
    quantity: int
    threshold: int


@dataclass(frozen=True, slots=True)
class OrderCreated(DomainEvent):
    """Published after an order is created (status CREATED)."""

    business_id: int
    order_id: int
    customer_id: int


@dataclass(frozen=True, slots=True)
class OrderConfirmed(DomainEvent):
    """Published after an order is confirmed (inventory decremented)."""

    business_id: int
    order_id: int
    customer_id: int


@dataclass(frozen=True, slots=True)
class OrderCancelled(DomainEvent):
    """Published after an order is cancelled (inventory restored if it had been decremented)."""

    business_id: int
    order_id: int
    customer_id: int


@dataclass(frozen=True, slots=True)
class PaymentSucceeded(DomainEvent):
    """Published after a payment is verified successful and the order reaches PAID."""

    business_id: int
    order_id: int
    payment_id: int


@dataclass(frozen=True, slots=True)
class PaymentFailed(DomainEvent):
    """Published after a payment attempt fails verification."""

    business_id: int
    order_id: int
    payment_id: int
    failure_code: str


E = TypeVar("E", bound=DomainEvent)
Handler = Callable[[DomainEvent], None]


class EventBus:
    """A minimal synchronous in-process event bus."""

    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        # Stored under the concrete type; the cast is safe because publish only
        # dispatches events of exactly ``event_type`` to this handler.
        self._handlers[event_type].append(handler)  # type: ignore[arg-type]

    def publish(self, event: DomainEvent) -> None:
        for handler in self._handlers.get(type(event), []):
            try:
                handler(event)
            except Exception:  # isolate handler failures from the publisher
                logger.exception("event handler failed for %s", type(event).__name__)

    def clear(self) -> None:
        """Remove all subscriptions (used by tests for isolation)."""
        self._handlers.clear()


# Process-wide bus. Injected into services via app wiring / FastAPI dependencies.
event_bus = EventBus()
