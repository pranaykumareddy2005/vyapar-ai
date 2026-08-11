"""Notification API - thin controllers over NotificationService.

business_id comes from the authenticated principal only. Notifications are
operational business alerts readable by any authenticated business user; every
query is tenant-scoped.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import Principal, get_current_principal
from app.notification.dependencies import get_notification_service
from app.notification.schemas import MarkedReadOut, NotificationOut
from app.notification.service import NotificationService

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = Query(default=False),
    principal: Principal = Depends(get_current_principal),
    service: NotificationService = Depends(get_notification_service),
) -> list[NotificationOut]:
    return [
        NotificationOut.from_model(n)
        for n in service.list_notifications(principal.business_id, unread_only=unread_only)
    ]


@router.get("/{notification_id}", response_model=NotificationOut)
def get_notification(
    notification_id: int,
    principal: Principal = Depends(get_current_principal),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationOut:
    return NotificationOut.from_model(service.get(principal.business_id, notification_id))


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    principal: Principal = Depends(get_current_principal),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationOut:
    return NotificationOut.from_model(service.mark_read(principal.business_id, notification_id))


@router.post("/read-all", response_model=MarkedReadOut)
def mark_all_read(
    principal: Principal = Depends(get_current_principal),
    service: NotificationService = Depends(get_notification_service),
) -> MarkedReadOut:
    return MarkedReadOut(updated=service.mark_all_read(principal.business_id))
