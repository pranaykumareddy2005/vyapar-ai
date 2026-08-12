# Phase 10 — Schema Decision

Only one new table is required (Notifications). Analytics and Dashboard are
**read-only** over existing transactional tables — **no new tables, no analytics
read-models, no materialized views** (§19/§35). No changes to any existing table.

## `notification`

Tenant-scoped in-app notification persisted from a domain event.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `business_id` | BIGINT NOT NULL → `business(id)` CASCADE | tenant key (from the event, never client) |
| `type` | VARCHAR(20) NOT NULL | `LOW_STOCK / ORDER_CREATED / ORDER_CONFIRMED / ORDER_CANCELLED / PAYMENT_SUCCESS / PAYMENT_FAILED` |
| `title` | VARCHAR(200) NOT NULL | deterministic, from the event |
| `body` | VARCHAR(500) NOT NULL | deterministic, minimal business info (no secrets/PII beyond what's needed) |
| `related_entity_type` | VARCHAR(20) NULL | `product / order / payment` |
| `related_entity_id` | BIGINT NULL | id of the related domain entity |
| `is_read` | BOOLEAN NOT NULL DEFAULT false | business-wide read state |
| `read_at` | TIMESTAMPTZ NULL | |
| `dedup_key` | VARCHAR(120) NULL | idempotency key (see below) |
| `created_at`, `updated_at` | TIMESTAMPTZ | TimestampMixin |

Constraints / indexes:
- FK `business_id` → `business(id)` ON DELETE CASCADE.
- Partial unique `uq_notification_dedup (business_id, dedup_key) WHERE dedup_key IS NOT NULL`
  — enforces one notification per logical event (order/payment) and one low-stock
  per product; concurrent duplicate events hit this and are skipped.
- Index `ix_notification_business_created (business_id, created_at DESC)` — the
  primary listing/order-by path (recent first), tenant-filtered.
- Index `ix_notification_business_read (business_id, is_read)` — unread counts/filter.

Dedup key values: `"{TYPE}:{order_id}"` for order events, `"{TYPE}:{payment_id}"`
for payment events, `"LOW_STOCK:{product_id}"` for low-stock.

## No other schema changes

Analytics/Dashboard query `orders`, `order_item`, `payment`, `inventory`,
`customer` directly (read-only aggregation). Existing indexes already cover the
tenant-scoped, status-filtered access paths added in Phases 3–9
(`ix_orders_business_status`, `ix_orders_business_id`, `ix_order_item_business_order`,
`ix_inventory_business_id`, `ix_payment_business_id`); no speculative indexes are
added (§27).
