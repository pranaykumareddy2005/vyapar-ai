"""Pydantic schemas for the notification API edge."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.notification.models import Notification


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    type: str
    title: str
    body: str
    related_entity_type: str | None
    related_entity_id: int | None
    is_read: bool
    created_at: datetime

    @classmethod
    def from_model(cls, notification: Notification) -> NotificationOut:
        return cls(
            id=notification.id,
            business_id=notification.business_id,
            type=notification.type.value,
            title=notification.title,
            body=notification.body,
            related_entity_type=notification.related_entity_type,
            related_entity_id=notification.related_entity_id,
            is_read=notification.is_read,
            created_at=notification.created_at,
        )


class MarkedReadOut(BaseModel):
    updated: int
