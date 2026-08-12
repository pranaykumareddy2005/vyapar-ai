"""AnalyticsService - read-only business metrics via PostgreSQL aggregation.

Read-only: it never writes to any table. Financial values come from authoritative
Decimal columns (order totals, payment amounts). Sales count orders that reached a
paid-or-later, non-cancelled state; payment totals use successful Payment rows;
low-stock uses the same ``quantity <= low_stock_threshold`` rule as InventoryService;
top products use the immutable OrderItem snapshots. Semantics are documented in
docs/history/phase10_architecture_decision.md.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.periods import Period, resolve_period
from app.analytics.schemas import LowStockItem, PaymentTotals, SalesSummary, TopProduct
from app.inventory.models import Inventory
from app.order.models import Order, OrderItem, OrderStatus
from app.payment.models import Payment, PaymentStatus

# Orders that count as sales/revenue: paid or a later fulfillment state (money
# received), never CANCELLED/CREATED/CONFIRMED.
SALES_STATES: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.PAID,
        OrderStatus.PACKED,
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
        OrderStatus.COMPLETED,
    }
)


def _dec(value: object) -> Decimal:
    # Quantize to 2 dp so money is always e.g. "0.00" (matches NUMERIC(12,2)).
    return Decimal(str(value if value is not None else "0")).quantize(Decimal("0.01"))


class AnalyticsService:
    def __init__(self, session: Session, *, currency: str, timezone: str) -> None:
        self._session = session
        self._currency = currency
        self._tz = timezone

    def _range(
        self, period: Period, now: datetime | None
    ) -> tuple[datetime | None, datetime | None]:
        return resolve_period(period, self._tz, now=now)

    # --- sales / revenue --------------------------------------------------

    def sales_summary(
        self, business_id: int, period: Period, *, now: datetime | None = None
    ) -> SalesSummary:
        start, end = self._range(period, now)
        stmt = select(func.coalesce(func.sum(Order.total_amt), 0), func.count()).where(
            Order.business_id == business_id, Order.status.in_(SALES_STATES)
        )
        if start is not None:
            stmt = stmt.where(Order.created_at >= start)
        if end is not None:
            stmt = stmt.where(Order.created_at < end)
        revenue, count = self._session.execute(stmt).one()
        return SalesSummary(
            period=period.value,
            order_count=int(count),
            revenue=_dec(revenue),
            currency=self._currency,
        )

    def order_counts_by_status(self, business_id: int) -> dict[str, int]:
        stmt = (
            select(Order.status, func.count())
            .where(Order.business_id == business_id)
            .group_by(Order.status)
        )
        counts = {status.value: 0 for status in OrderStatus}
        for status, count in self._session.execute(stmt):
            counts[status.value] = int(count)
        return counts

    # --- top products (units sold, from OrderItem snapshots) --------------

    def top_products(self, business_id: int, *, limit: int = 5) -> list[TopProduct]:
        units = func.sum(OrderItem.quantity)
        revenue = func.sum(OrderItem.unit_price * OrderItem.quantity)
        stmt = (
            select(OrderItem.product_name, units, revenue)
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.business_id == business_id, Order.status.in_(SALES_STATES))
            .group_by(OrderItem.product_name)
            .order_by(units.desc())
            .limit(limit)
        )
        return [
            TopProduct(product_name=name, units_sold=int(u), revenue=_dec(r))
            for name, u, r in self._session.execute(stmt)
        ]

    # --- inventory --------------------------------------------------------

    def low_stock_count(self, business_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Inventory)
            .where(
                Inventory.business_id == business_id,
                Inventory.quantity <= Inventory.low_stock_threshold,
            )
        )
        return int(self._session.execute(stmt).scalar_one())

    def low_stock_items(self, business_id: int, *, limit: int = 20) -> list[LowStockItem]:
        stmt = (
            select(Inventory)
            .where(
                Inventory.business_id == business_id,
                Inventory.quantity <= Inventory.low_stock_threshold,
            )
            .order_by(Inventory.quantity)
            .limit(limit)
        )
        return [
            LowStockItem(
                inventory_id=inv.id,
                product_id=inv.product_id,
                quantity=inv.quantity,
                low_stock_threshold=inv.low_stock_threshold,
            )
            for inv in self._session.scalars(stmt)
        ]

    # --- payments ---------------------------------------------------------

    def payment_totals(
        self, business_id: int, period: Period, *, now: datetime | None = None
    ) -> PaymentTotals:
        start, end = self._range(period, now)
        stmt = select(func.coalesce(func.sum(Payment.amount), 0), func.count()).where(
            Payment.business_id == business_id, Payment.status == PaymentStatus.SUCCESS
        )
        if start is not None:
            stmt = stmt.where(Payment.created_at >= start)
        if end is not None:
            stmt = stmt.where(Payment.created_at < end)
        total, count = self._session.execute(stmt).one()
        return PaymentTotals(
            period=period.value,
            successful_count=int(count),
            total=_dec(total),
            currency=self._currency,
        )
