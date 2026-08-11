"""Dashboard API - one read-only KPI summary. OWNER/ADMIN only (SDD §5).

Thin controller: it maps the DashboardService result to the response schema and
does no business logic. Tenant-scoped by the authenticated principal.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import Principal, require_role
from app.common.security import Role
from app.dashboard.dependencies import get_dashboard_service
from app.dashboard.service import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_VIEWER_ROLES = (Role.OWNER, Role.ADMIN)


class SalesBlock(BaseModel):
    period: str
    order_count: int
    revenue: Decimal
    currency: str


class TopProductBlock(BaseModel):
    product_name: str
    units_sold: int
    revenue: Decimal


class LowStockBlock(BaseModel):
    inventory_id: int
    product_id: int
    quantity: int
    low_stock_threshold: int


class RecentOrderBlock(BaseModel):
    id: int
    status: str
    total: Decimal


class DashboardOut(BaseModel):
    sales_today: SalesBlock
    sales_month: SalesBlock
    order_counts: dict[str, int]
    low_stock_count: int
    low_stock_items: list[LowStockBlock]
    top_products: list[TopProductBlock]
    recent_orders: list[RecentOrderBlock]
    unread_notifications: int


@router.get("/summary", response_model=DashboardOut)
def dashboard_summary(
    principal: Principal = Depends(require_role(*_VIEWER_ROLES)),
    service: DashboardService = Depends(get_dashboard_service),
) -> DashboardOut:
    s = service.summary(principal.business_id)
    return DashboardOut(
        sales_today=SalesBlock(
            period=s.sales_today.period,
            order_count=s.sales_today.order_count,
            revenue=s.sales_today.revenue,
            currency=s.sales_today.currency,
        ),
        sales_month=SalesBlock(
            period=s.sales_month.period,
            order_count=s.sales_month.order_count,
            revenue=s.sales_month.revenue,
            currency=s.sales_month.currency,
        ),
        order_counts=s.order_counts,
        low_stock_count=s.low_stock_count,
        low_stock_items=[
            LowStockBlock(
                inventory_id=i.inventory_id,
                product_id=i.product_id,
                quantity=i.quantity,
                low_stock_threshold=i.low_stock_threshold,
            )
            for i in s.low_stock_items
        ],
        top_products=[
            TopProductBlock(product_name=p.product_name, units_sold=p.units_sold, revenue=p.revenue)
            for p in s.top_products
        ],
        recent_orders=[
            RecentOrderBlock(id=o.id, status=o.status, total=o.total) for o in s.recent_orders
        ],
        unread_notifications=s.unread_notifications,
    )
