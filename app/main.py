"""FastAPI application entrypoint (modular monolith).

Builds the application in :func:`create_app`: configures the app from settings,
registers error handlers and every domain router, and exposes the ``/healthz``
probe. The development message-simulation endpoint is mounted only outside
production. The notification event listener is subscribed once at import time
(see :func:`_wire_notifications`).
"""

from __future__ import annotations

from fastapi import FastAPI

from app.common.error_handlers import register_error_handlers
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.debug,
    )

    register_error_handlers(app)

    from app.analytics.router import router as analytics_router
    from app.auth.router import router as auth_router
    from app.business.router import router as business_router
    from app.catalog.router import router as catalog_router
    from app.catalogai.router import router as catalog_ai_router
    from app.conversation.router import router as conversation_router
    from app.customer.router import router as customer_router
    from app.dashboard.router import router as dashboard_router
    from app.inventory.router import router as inventory_router
    from app.invoice.router import router as invoice_router
    from app.notification.router import router as notification_router
    from app.order.router import router as order_router
    from app.payment.router import router as payment_router
    from app.whatsapp.router import router as whatsapp_router

    app.include_router(auth_router)
    app.include_router(business_router)
    app.include_router(catalog_router)
    app.include_router(catalog_ai_router)
    app.include_router(inventory_router)
    app.include_router(conversation_router)
    app.include_router(customer_router)
    app.include_router(order_router)
    app.include_router(payment_router)
    app.include_router(invoice_router)
    app.include_router(notification_router)
    app.include_router(analytics_router)
    app.include_router(dashboard_router)
    # Public inbound channel (Meta cannot present a JWT); trust via verify token
    # + request signature, enforced inside the router.
    app.include_router(whatsapp_router)

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        """Liveness/readiness probe used by Docker and the deploy runbook."""
        return {"status": "ok", "environment": settings.environment}

    # Mount the dev simulation endpoint outside production only.
    if not settings.is_production:
        from app.dev_sim import router as dev_router

        app.include_router(dev_router)

    return app


def _wire_notifications() -> None:
    """Subscribe the notification listener to the EventBus exactly once.

    Registered at module import (not per ``create_app``) so handlers are not
    duplicated across the many ``create_app`` calls in tests. Gated by
    ``notifications_enabled`` (disabled in the test env so the rolled-back test
    session is never touched by the independent-session listener).
    """
    settings = get_settings()
    if not settings.notifications_enabled:
        return
    from app.common.events import event_bus
    from app.db import SessionLocal
    from app.notification.listener import NotificationEventListener

    NotificationEventListener(SessionLocal).register(event_bus)


app = create_app()
_wire_notifications()
