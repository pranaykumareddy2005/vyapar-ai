# Phase 7 — Customer + Order Management: Schema Consistency & Decision Report

Reviewed against: SRS §4.7 (FR-ORD-01..05) & UC-04, SDD §4.1 (entity dictionary),
§7.7, LLD §2.2, §5.1 (transition table), §7.3 (order total & tax), §8 (DDL), and
the Phase 1–6 code (Money, EventBus, CatalogService, InventoryService).

## 1. What the design says

- **FR-ORD-01..05**: cart items + quantities; apply tax/discount; lifecycle
  `created → confirmed → paid → packed → shipped → delivered → completed`;
  customer profile with history + saved addresses; **decrement inventory on confirm**.
- **SDD §4.1 entity dictionary**: `Customer(id, business_id, name, phone)` "keyed by
  phone"; `Address(id, customer_id, line, city, pin)`; `Order(id, business_id,
  customer_id, status, total, tax, created_at)`; `OrderItem(id, order_id, product_id,
  qty, price)` "price captured at sale".
- **LLD §5.1 transition table** (the guarded state machine):
  `created —confirm→ confirmed` (stock available → decrement); `created —cancel→
  cancelled` (release holds); `confirmed —pay/COD→ paid`; `confirmed —cancel→
  cancelled` (restore inventory); `paid —pack→ packed`; `packed —ship→ shipped`;
  `shipped —deliver→ delivered`; `delivered —close→ completed` (final).
- **LLD §7.3**: `goods = Σ(qty·price)`, `tax = round(goods·TAX_RATE, 2)`, `total = goods + tax`.
- **SDD §7.7**: OrderService owns totals + state machine; on confirmation inventory
  decremented **atomically**; CustomerService owns profiles/addresses/history.

## 2. Decisions

| # | Topic | Decision |
|---|-------|----------|
| D1 | Modules | Two modules: `app/customer/` (Customer, Address) and `app/order/` (Order, OrderItem, lifecycle). Order depends on Customer + Catalog + Inventory; none depend on Order. |
| D2 | Customer uniqueness (§7) | Phone unique **per business among active customers** — partial unique index `(business_id, phone) WHERE is_deleted = false`. Not global (mirrors the Phase-3 SKU decision). |
| D3 | Customer soft delete (§23) | `is_deleted` flag. Soft-deleted customers are excluded from listings but still referenced by historical orders (FK `RESTRICT`), so order history is never destroyed. |
| D4 | Address | Implemented minimally per the entity dictionary + FR-ORD-04 (saved addresses): `customer_address(id, business_id, customer_id, line, city, pin)`, create/list nested under a customer. Orders do **not** reference an address (SDD Order has no address_id). |
| D5 | OrderItem snapshot (§9/§20) | Snapshot **both `unit_price` and `product_name`** at sale. Justification: §20 requires historical correctness when the product's name/price changes or it is soft-deleted; reading the live `Product` would violate that. The SDD lists "price captured at sale" as the principle — the product_name snapshot directly serves the stated requirement. `product_id` is retained as a reference (FK `RESTRICT`). |
| D6 | Order money fields | Store `tax_amt` and `total_amt` (NUMERIC(12,2), per SDD). Subtotal is derivable (`Σ line_total` or `total − tax`); no separate column. All arithmetic via the existing `Money` value object (Decimal, never float). |
| D7 | Discount (§4/§11) | The approved data model (SDD entity dictionary) has **no discount column**; FR-ORD-02 mentions discounts but the schema does not model them. Decision: apply **tax only** (LLD §7.3, `default_tax_rate` from config); order-level discounts are **deferred** (no invented field). Documented conflict resolved in favor of the authoritative data model. |
| D8 | OrderItem tenant key | Denormalize `business_id` onto `order_item` (as `product_image`/`stock_movement` do) for tenant-safe direct queries. |
| D9 | Inventory timing (§12) | Inventory is **decremented on confirm** and **restored on cancel-from-confirmed** (FR-ORD-05, §5.1). Order creation reserves nothing (created state); stock is validated at confirm. No new reservation system. |
| D10 | Transaction boundary (§13) | `OrderService` owns the confirm/cancel transaction. Phase-5 `InventoryService` gains a **non-committing composable primitive** `stage_adjustment(...)` (locks the row `FOR UPDATE`, validates, writes quantity + movement, returns a pending `LowStock` or `None`, **does not commit**). OrderService stages all item adjustments + the status change and commits **once**, then publishes events. This is the "controlled application-level transaction boundary" §13 invites — it **preserves** Phase-5 row-locking and the single-write-authority (all inventory writes still go through InventoryService). Existing `adjust_stock`/`adjust_stock_by_product` are unchanged. |
| D11 | Cancel restoration movement | Restoring stock on cancel uses `MovementType.RESTOCK` (closest approved type; stock increases). No new movement type invented. |
| D12 | State machine (§15) | `OrderStatus` = CREATED/CONFIRMED/PAID/PACKED/SHIPPED/DELIVERED/COMPLETED/CANCELLED; `OrderEvent` = CONFIRM/CANCEL/PAY/PACK/SHIP/DELIVER/CLOSE. A single guarded transition table; any `(status, event)` not in it → `ConflictError`. One `POST /api/orders/{id}/transition` endpoint (validated event), never a raw status write. |
| D13 | Payment separation (§16) | `pay` transition just moves `confirmed → paid` (represents COD acceptance / external confirmation) — **no** Razorpay, no payment tables, no payment processing. Order status ≠ payment status. |
| D14 | RBAC (§21) | Mutations (create/update/delete customer, add address, create order, transition) → OWNER/EMPLOYEE; reads → any authenticated principal; **ADMIN denied** mutations. Matches the Phase 3–5 policy. |
| D15 | Business PIN (§22) | Order/customer operations are not FR-AUTH-03 destructive actions → **no PIN**. |
| D16 | Idempotency (§27) | No idempotency key for order creation (not required by the SRS; documented). Cancellation is **idempotent by construction**: CANCELLED is terminal, so a second CANCEL is an invalid transition → rejected → stock never restored twice. |
| D17 | Events (§26) | Add `OrderCreated`, `OrderConfirmed`, `OrderCancelled` to the Phase-1 `EventBus` (published post-commit) — genuinely useful for the future Notification module (SDD §7.10). No broker. |

## 3. Final schemas

**`customer`**: `id` PK; `business_id` FK business CASCADE; `name` VARCHAR(200);
`phone` VARCHAR(20); `is_deleted` bool default false; timestamps. Partial unique
`(business_id, phone) WHERE is_deleted=false`; index `(business_id)`.

**`customer_address`**: `id` PK; `business_id` FK business CASCADE; `customer_id`
FK customer CASCADE; `line` VARCHAR(300); `city` VARCHAR(100); `pin` VARCHAR(12);
timestamps. Index `(business_id, customer_id)`.

**`orders`**: `id` PK; `business_id` FK business CASCADE; `customer_id` FK customer
RESTRICT; `status` VARCHAR(20) (enum); `tax_amt` NUMERIC(12,2); `total_amt`
NUMERIC(12,2); timestamps. Indexes `(business_id)`, `(business_id, status)`,
`(business_id, customer_id)`.

**`order_item`**: `id` PK; `business_id` FK business CASCADE; `order_id` FK orders
CASCADE; `product_id` FK product RESTRICT; `product_name` VARCHAR(200) (snapshot);
`unit_price` NUMERIC(12,2) (snapshot); `quantity` INT (`CHECK > 0`); timestamps.
Index `(business_id, order_id)`.

## 4. Confirm/cancel flow (atomic)

```
confirm(order in CREATED):
  one transaction:
    for item: InventoryService.stage_adjustment(business_id, product_id, -qty, SALE)  # row-locked, no commit
    order.status = CONFIRMED
    commit ONCE
  publish pending LowStock events + OrderConfirmed
cancel(order in CONFIRMED):  restore +qty (RESTOCK) for each item, status=CANCELLED, commit once, publish OrderCancelled
cancel(order in CREATED):    status=CANCELLED only (nothing was decremented)
```

Competing confirmations serialize on the inventory row lock (`FOR UPDATE`), so two
orders cannot oversell the same stock — verified by a real-PostgreSQL concurrency
test.
