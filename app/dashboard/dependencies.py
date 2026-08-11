"""FastAPI wiring for the dashboard service."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.analytics.service import AnalyticsService
from app.config import Settings, get_settings
from app.dashboard.service import DashboardService
from app.db import get_session
from app.notification.repository import NotificationRepository
from app.order.repository import OrderRepository


def get_dashboard_service(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> DashboardService:
    analytics = AnalyticsService(
        session, currency=settings.default_currency, timezone=settings.business_timezone
    )
    return DashboardService(
        analytics,
        OrderRepository(session),
        NotificationRepository(session),
    )
