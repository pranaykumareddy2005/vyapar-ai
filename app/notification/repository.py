"""Notification persistence. Tenant-scoped by ``business_id``; persistence-only."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.notification.models import Notification


class NotificationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, notification: Notification) -> Notification:
        self._session.add(notification)
        self._session.flush()
        return notification

    def get(self, business_id: int, notification_id: int) -> Notification | None:
        stmt = select(Notification).where(
            Notification.id == notification_id, Notification.business_id == business_id
        )
        return self._session.scalars(stmt).one_or_none()

    def list(
        self, business_id: int, *, unread_only: bool = False, limit: int = 50
    ) -> list[Notification]:
        stmt = select(Notification).where(Notification.business_id == business_id)
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
        return list(self._session.scalars(stmt).all())

    def unread_count(self, business_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.business_id == business_id, Notification.is_read.is_(False))
        )
        return self._session.execute(stmt).scalar_one()

    def mark_all_read(self, business_id: int) -> int:
        stmt = (
            update(Notification)
            .where(Notification.business_id == business_id, Notification.is_read.is_(False))
            .values(is_read=True, read_at=datetime.now(UTC))
        )
        result = self._session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)
