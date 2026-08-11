"""DashboardService - read-only composition of analytics + domain reads.

Delegates all metric computation to AnalyticsService (the read-model authority) and
reads recent orders / unread-notification count through repositories. It performs no
business calculations of its own and mutates nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.analytics.periods import Period
from app.analytics.schemas import LowStockItem, SalesSummary, TopProduct
from app.analytics.service import AnalyticsService
from app.notification.repository import NotificationRepository
from app.order.repository import OrderRepository

_RECENT_ORDER_LIMIT = 5
_TOP_PRODUCT_LIMIT = 5
_LOW_STOCK_LIMIT = 5


@dataclass(frozen=True, slots=True)
class RecentOrder:
    id: int
    status: str
    total: Decimal


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    sales_today: SalesSummary
    sales_month: SalesSummary
    order_counts: dict[str, int]
    low_stock_count: int
    low_stock_items: list[LowStockItem]
    top_products: list[TopProduct]
    recent_orders: list[RecentOrder]
    unread_notifications: int


class DashboardService:
    def __init__(
        self,
        analytics: AnalyticsService,
        orders: OrderRepository,
        notifications: NotificationRepository,
    ) -> None:
        self._analytics = analytics
        self._orders = orders
        self._notifications = notifications

    def summary(self, business_id: int) -> DashboardSummary:
        recent = self._orders.list(business_id)[:_RECENT_ORDER_LIMIT]
        return DashboardSummary(
            sales_today=self._analytics.sales_summary(business_id, Period.TODAY),
            sales_month=self._analytics.sales_summary(business_id, Period.MONTH),
            order_counts=self._analytics.order_counts_by_status(business_id),
            low_stock_count=self._analytics.low_stock_count(business_id),
            low_stock_items=self._analytics.low_stock_items(business_id, limit=_LOW_STOCK_LIMIT),
            top_products=self._analytics.top_products(business_id, limit=_TOP_PRODUCT_LIMIT),
            recent_orders=[
                RecentOrder(id=o.id, status=o.status.value, total=o.total_amt) for o in recent
            ],
            unread_notifications=self._notifications.unread_count(business_id),
        )
