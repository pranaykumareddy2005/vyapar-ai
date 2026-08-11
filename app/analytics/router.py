"""Analytics API - read-only KPIs. OWNER/ADMIN only (SDD §5).

business_id comes from the authenticated principal; all queries are tenant-scoped.
No endpoint mutates any domain data, and no raw SQL/column selection is exposed.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.analytics.dependencies import get_analytics_service
from app.analytics.periods import Period
from app.analytics.service import AnalyticsService
from app.auth.dependencies import Principal, require_role
from app.common.security import Role

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_VIEWER_ROLES = (Role.OWNER, Role.ADMIN)


class SalesSummaryOut(BaseModel):
    period: str
    order_count: int
    revenue: Decimal
    currency: str


class TopProductOut(BaseModel):
    product_name: str
    units_sold: int
    revenue: Decimal


@router.get("/sales", response_model=SalesSummaryOut)
def sales(
    period: Period = Period.TODAY,
    principal: Principal = Depends(require_role(*_VIEWER_ROLES)),
    service: AnalyticsService = Depends(get_analytics_service),
) -> SalesSummaryOut:
    summary = service.sales_summary(principal.business_id, period)
    return SalesSummaryOut(
        period=summary.period,
        order_count=summary.order_count,
        revenue=summary.revenue,
        currency=summary.currency,
    )


@router.get("/top-products", response_model=list[TopProductOut])
def top_products(
    limit: int = 5,
    principal: Principal = Depends(require_role(*_VIEWER_ROLES)),
    service: AnalyticsService = Depends(get_analytics_service),
) -> list[TopProductOut]:
    return [
        TopProductOut(product_name=p.product_name, units_sold=p.units_sold, revenue=p.revenue)
        for p in service.top_products(principal.business_id, limit=max(1, min(limit, 50)))
    ]
