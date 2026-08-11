"""FastAPI wiring for the analytics service."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.analytics.service import AnalyticsService
from app.config import Settings, get_settings
from app.db import get_session


def get_analytics_service(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AnalyticsService:
    return AnalyticsService(
        session, currency=settings.default_currency, timezone=settings.business_timezone
    )
