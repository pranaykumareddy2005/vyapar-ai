"""FastAPI application entrypoint (modular monolith).

Domain routers are mounted here as each module is built (Phase 2+). Phase 1
wires only health, error handling, and the development simulation endpoint.
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

    from app.auth.router import router as auth_router
    from app.business.router import router as business_router
    from app.catalog.router import router as catalog_router
    from app.catalogai.router import router as catalog_ai_router
    from app.conversation.router import router as conversation_router
    from app.customer.router import router as customer_router
    from app.inventory.router import router as inventory_router
    from app.invoice.router import router as invoice_router
    from app.order.router import router as order_router
    from app.payment.router import router as payment_router

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

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        """Liveness/readiness probe used by Docker and the deploy runbook."""
        return {"status": "ok", "environment": settings.environment}

    # Mount the dev simulation endpoint outside production only.
    if not settings.is_production:
        from app.dev_sim import router as dev_router

        app.include_router(dev_router)

    return app


app = create_app()
