"""Notification application service - owns notification business rules.

Creates notifications from event drafts idempotently (duplicate/concurrent events
are absorbed by the ``dedup_key`` unique index) and exposes read/ack operations.
It never touches Order/Payment/Inventory/Invoice state.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.exceptions import NotFoundError
from app.notification.messages import NotificationDraft
from app.notification.models import Notification
from app.notification.repository import NotificationRepository


class NotificationService:
    def __init__(self, session: Session, notifications: NotificationRepository) -> None:
        self._session = session
        self._notifications = notifications

    # --- creation (from a domain-event draft) -----------------------------

    def create_from_draft(self, draft: NotificationDraft) -> Notification | None:
        """Persist a notification for an event draft, idempotently.

        Returns the created notification, or ``None`` if an equivalent one already
        exists (dedup) - both are treated as success by the caller.
        """
        try:
            notification = self._notifications.add(
                Notification(
                    business_id=draft.business_id,
                    type=draft.type,
                    title=draft.title,
                    body=draft.body,
                    related_entity_type=draft.related_entity_type,
                    related_entity_id=draft.related_entity_id,
                    dedup_key=draft.dedup_key,
                )
            )
            self._session.commit()
        except IntegrityError:
            # Duplicate event (same dedup_key): already recorded - not an error.
            self._session.rollback()
            return None
        self._session.refresh(notification)
        return notification

    # --- reads / acknowledgement ------------------------------------------

    def get(self, business_id: int, notification_id: int) -> Notification:
        notification = self._notifications.get(business_id, notification_id)
        if notification is None:
            raise NotFoundError("notification not found")
        return notification

    def list_notifications(
        self, business_id: int, *, unread_only: bool = False
    ) -> list[Notification]:
        return self._notifications.list(business_id, unread_only=unread_only)

    def unread_count(self, business_id: int) -> int:
        return self._notifications.unread_count(business_id)

    def mark_read(self, business_id: int, notification_id: int) -> Notification:
        notification = self.get(business_id, notification_id)
        if not notification.is_read:
            try:
                notification.is_read = True
                notification.read_at = datetime.now(UTC)
                self._session.commit()
            except Exception:
                self._session.rollback()
                raise
            self._session.refresh(notification)
        return notification

    def mark_all_read(self, business_id: int) -> int:
        try:
            count = self._notifications.mark_all_read(business_id)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return count
