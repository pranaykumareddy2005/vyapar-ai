# Phase 10 — Notifications, Analytics & Dashboard: Architecture Decision

Reviewed against: SRS §4.10 (FR-NOT-01..03), §4.11 (FR-DASH-01..04), AC-08, SDD §5
(API roles), §7.10 (Notification), §7.11 (Analytics), the Phase-1 EventBus, and the
Phase 1–9 code (events already emitted, Money, ObjectStorage, Redis, RBAC).

## 1. What the design says

- **FR-NOT-01**: notify on **order and payment status changes** (High). **FR-NOT-02**:
  notify the merchant of **low-stock** (Medium). **FR-NOT-03**: **email fallback** (Low).
- **SDD §7.10**: `NotificationService` consumes domain events and dispatches across
  WhatsApp/email channels (channels are external; **out of Phase-10 scope**).
- **FR-DASH-01**: dashboard to manage products/inventory/customers/orders (High).
  **FR-DASH-02**: display **daily and monthly sales, revenue and top products
  computed from order data** (Medium). **FR-DASH-03**: **restrict by role** (High).
  **FR-DASH-04**: render analytics as charts (Medium — frontend; backend supplies data).
- **SDD §5 (API roles)**: `GET /api/analytics/sales` → **OWNER/ADMIN**.
- **SDD §7.11**: analytics = **SQL-computed** sales, revenue, top products.
- **Existing events** (all post-commit, in-process EventBus): `LowStock`,
  `OrderCreated`, `OrderConfirmed`, `OrderCancelled`, `PaymentSucceeded`,
  `PaymentFailed`. **No new events are required** (§6).

## 2. Decisions

| # | Topic | Decision |
|---|-------|----------|
| D1 | Notification channel | **In-app persisted notifications only.** WhatsApp/email delivery (FR-NOT-01/02/03 channels) is **deferred** (WhatsApp/Meta not in scope; email is Low priority). No external `NotificationProvider` invented (§12) — a provider seam would be architectural appearance without a required channel. |
| D2 | Event → notification | A `NotificationEventListener` subscribes to the **existing EventBus**; on each event it calls `NotificationService` to persist a notification. Transactional domains are **not** modified (they already publish); no notification code lives in Order/Payment/Inventory (§11/§16/§17). |
| D3 | Event timing / durability | Notifications are created **post-commit, best-effort**: the listener opens its **own `SessionLocal`** so a notification write can never roll back or fail a committed domain change (§7/§38). **Limitation (documented, not hidden):** the in-process EventBus has no outbox, so a crash between the domain commit and the notification write loses that one notification. This is **not durable messaging**; no broker/outbox is introduced (§7). |
| D4 | Notification types | Exactly the required sources: `LOW_STOCK`, `ORDER_CREATED`, `ORDER_CONFIRMED`, `ORDER_CANCELLED`, `PAYMENT_SUCCESS`, `PAYMENT_FAILED`. No `INVOICE_ISSUED` (FR-NOT-01 covers order+payment only; invoice sharing is a WhatsApp delivery concern, deferred). |
| D5 | Recipient model | **Business-wide** notifications, tenant-scoped by `business_id` from the event (never client input). MVP is single-merchant (SRS §2.5), so read/unread state is **business-wide** (not per-user). Documented (§37). |
| D6 | Deduplication | DB **partial-unique `dedup_key`** per business. Order/payment events → `dedup_key = "{type}:{entity_id}"` (idempotent: one notification per order-event/payment-event). Low-stock → `dedup_key = "LOW_STOCK:{product_id}"` (one low-stock notification per product). **Documented MVP limitation:** a product restocked and dropping low again does not re-alert; this avoids spam without a stateful re-arming mechanism (§14). Concurrent duplicate events → unique violation caught → skip. |
| D7 | Notification RBAC | Reads/ack require any authenticated business user (OWNER/EMPLOYEE/ADMIN) — operational alerts, tenant-scoped. |
| D8 | Analytics store | **PostgreSQL aggregation over existing transactional tables** — no analytics tables, no warehouse, no ML (§19/§27). Read-only. |
| D9 | Sales semantics | **Revenue = SUM(`order.total_amt`) for orders in a paid-or-later, non-cancelled state**: `{PAID, PACKED, SHIPPED, DELIVERED, COMPLETED}` (money received). Consistent everywhere (dashboard + analytics). Documented (§23). Uses the authoritative Order total (never recomputed; Decimal). |
| D10 | Payment analytics | Uses **Payment** as authority: SUM(`payment.amount`) where `status='SUCCESS'` (never inferred from Order.status; failed/duplicate attempts excluded — one SUCCESS per order by Phase-8 constraint) (§24). |
| D11 | Inventory analytics | Low-stock = `quantity <= low_stock_threshold` over the `inventory` table — the **same** definition as InventoryService (§25). Current quantity read from `inventory` (not replayed from movements). |
| D12 | Top products | **Units sold**: SUM(`order_item.quantity`) grouped by `product_name` (the OrderItem snapshot, never live Product) for items of PAID+ orders (CANCELLED excluded). Also returns snapshot revenue (SUM `line_total`). Documented (§26). |
| D13 | Time semantics | Two periods for the dashboard (FR-DASH-02): **today** and **this month**, plus an all-time total. Boundaries computed in a configurable **`business_timezone`** (default `UTC`), then converted to a UTC `created_at` range — no silent UTC/local mixing (§22). |
| D14 | Analytics/Dashboard RBAC | **OWNER/ADMIN** (per SDD §5); EMPLOYEE denied (financial data). Enforced with the existing `require_role`. |
| D15 | Dashboard architecture | `DashboardService` composes `AnalyticsService` results + recent orders (via `OrderRepository`) + low-stock (analytics) + unread-notification count (via `NotificationRepository`) into one KPI response. Read-only; thin router; no business mutation; no ORM math in the router (§30). |
| D16 | Caching | **None.** Redis is used only for the auth refresh-token store; PostgreSQL aggregation is sufficient at MVP scale. No dashboard/analytics caching (§33). |
| D17 | New events / infra | **None.** All source events already exist; no broker, outbox, warehouse, or job framework (§0/§6/§7). |

## 3. Modules & dependency direction

```
existing domain services --(existing events)--> EventBus --> NotificationEventListener --> NotificationService --> NotificationRepository
existing transactional tables --> AnalyticsService (read-only SQL) --> Analytics API
AnalyticsService + OrderRepository(read) + NotificationRepository(read) --> DashboardService --> Dashboard API
```

NotificationService, AnalyticsService, and DashboardService are independent
responsibilities (§34): Dashboard reads Analytics; Analytics does not depend on
Notifications.

## 4. APIs

- Notifications: `GET /api/notifications`, `GET /api/notifications/{id}`,
  `POST /api/notifications/{id}/read`, `POST /api/notifications/read-all` (any
  authenticated business user).
- Analytics: `GET /api/analytics/sales?period=today|month|all`,
  `GET /api/analytics/top-products` (OWNER/ADMIN).
- Dashboard: `GET /api/dashboard/summary` (OWNER/ADMIN).

## 5. Testing note (event listener)

The listener writes via its own `SessionLocal` (post-commit). To keep the existing
rolled-back-session suite clean, the global subscription is gated by
`NOTIFICATIONS_ENABLED` (off in the test env). Notification behavior is tested two
ways: (a) event → notification through the real listener/service against committed
PostgreSQL data (the concurrency-test pattern), and (b) the read/ack/security APIs
by inserting notifications through the repository in the standard test session.
