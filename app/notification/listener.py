"""Event -> notification wiring.

Subscribes to the in-process EventBus. Each handler runs post-commit (the
producing domain service publishes after its own commit) and opens its OWN session
from a factory, so a notification write can never roll back or fail the committed
domain change. Handler failures are isolated by the EventBus and additionally
guarded here, so notifications are strictly best-effort.

Limitation (documented): the in-process bus has no outbox, so a crash between the
domain commit and the notification write loses that one notification. This is not
durable messaging; no broker/outbox is introduced.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.common.events import (
    DomainEvent,
    EventBus,
    LowStock,
    OrderCancelled,
    OrderConfirmed,
    OrderCreated,
    PaymentFailed,
    PaymentSucceeded,
)
from app.notification import messages
from app.notification.messages import NotificationDraft
from app.notification.repository import NotificationRepository
from app.notification.service import NotificationService

logger = logging.getLogger(__name__)

# Event type -> pure draft builder.
_MAPPERS: dict[type[DomainEvent], Callable[[DomainEvent], NotificationDraft]] = {
    LowStock: messages.from_low_stock,  # type: ignore[dict-item]
    OrderCreated: messages.from_order_created,  # type: ignore[dict-item]
    OrderConfirmed: messages.from_order_confirmed,  # type: ignore[dict-item]
    OrderCancelled: messages.from_order_cancelled,  # type: ignore[dict-item]
    PaymentSucceeded: messages.from_payment_succeeded,  # type: ignore[dict-item]
    PaymentFailed: messages.from_payment_failed,  # type: ignore[dict-item]
}


class NotificationEventListener:
    """Bridges EventBus events to persisted notifications (best-effort)."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def handle(self, event: DomainEvent) -> None:
        mapper = _MAPPERS.get(type(event))
        if mapper is None:
            return
        draft = mapper(event)
        try:
            session = self._session_factory()
            try:
                NotificationService(session, NotificationRepository(session)).create_from_draft(
                    draft
                )
            finally:
                session.close()
        except Exception:  # never let a notification write disturb the caller
            logger.exception("failed to persist notification for %s", type(event).__name__)

    def register(self, bus: EventBus) -> None:
        for event_type in _MAPPERS:
            bus.subscribe(event_type, self.handle)
