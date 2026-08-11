"""FastAPI wiring for the notification service."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.notification.repository import NotificationRepository
from app.notification.service import NotificationService


def get_notification_service(session: Session = Depends(get_session)) -> NotificationService:
    return NotificationService(session, NotificationRepository(session))
