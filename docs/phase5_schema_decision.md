# Phase 5 — Inventory Management: Schema Consistency & Decision Report

Reviewed against: PDD §7.1(#5), SRS §4.5 (FR-INV) & UC-03, SDD §3.3/§5/§7.5,
LLD §2.1/§7.2/§8.1, Implementation Guide §5.3, and the Phase 1–4 code.

## 1. What the design says

- **LLD §2.1**: each `Product` owns exactly one `Inventory` (composition) and an
  append-only stream of `StockMovement` records. `Inventory.adjust(delta)` is the
  single choke-point; `Inventory.isLow()` is true when **quantity ≤ threshold**;
  `StockMovement` is immutable (no update methods).
- **LLD §7.2 / Impl §5.3** (atomic adjust): `begin tx → lockByProduct (row lock)
  → reject if quantity+delta < 0 → quantity += delta → append StockMovement →
  if quantity ≤ threshold publish LowStock → commit`.
- **LLD §8.1 DDL**: `inventory(id, product_id UNIQUE, quantity INT DEFAULT 0,
  threshold INT DEFAULT 0)`.
- **SDD §5 (API)**: `PATCH /api/inventory/{id}` — adjust stock — OWNER/EMPLOYEE.
- **SDD §7.5**: `InventoryController` (adjust/query), `InventoryService` (deltas,
  threshold checks), `InventoryRepository`/`StockMovementRepository`. Patterns:
  Repository, Observer (low-stock event), transactional update.
- **Phase-1 code**: `app/common/events.py::LowStock(business_id, product_id,
  quantity, threshold)` already exists — reused as-is.

## 2. Consistency findings & decisions

| # | Topic | Design | Phase-5 decision |
|---|-------|--------|------------------|
| D1 | `business_id` on inventory | LLD DDL has none | **Add** `business_id` to `inventory` and `stock_movement` (denormalized tenant key), matching the Phase-3 `product_image` pattern. Required for tenant-scoping (§6) and to avoid a join on every authz check. |
| D2 | Threshold field name | LLD calls it `threshold` | Name it **`low_stock_threshold`** per the Phase-5 spec §4 (clearer; the low-stock rule is unchanged: `quantity <= low_stock_threshold`). |
| D3 | Low-stock comparison | LLD `isLow()` = `quantity ≤ threshold` | **`quantity <= low_stock_threshold`** (kept exactly; never `<`). |
| D4 | Initial inventory creation | LLD models composition (product→inventory) | Inventory is created through the **Inventory boundary** (`POST /api/inventory`), NOT as a side effect of product creation. Reason: §24 forbids Catalog depending on Inventory; auto-creation in `CatalogService` would invert the approved dependency. The 1:1 relationship is enforced by a **unique constraint on `product_id`**, not by cascade-creation. |
| D5 | Adjust endpoint | SDD `PATCH /api/inventory/{id}` | Refined to `POST /api/inventory/{id}/adjust` (a non-idempotent action that creates a movement) and `PATCH /api/inventory/{id}` for threshold updates. Keeps routers thin and separates the two concerns. Minor, documented deviation from the SDD's single-line sketch. |
| D6 | Movement types | SDD/LLD examples: RESTOCK, SALE, MANUAL_ADJUSTMENT, DAMAGE | Exactly these 4 in a `MovementType` StrEnum. No larger enum invented (§10). |
| D7 | `resulting_quantity` on movement | not in LLD DDL | **Included** — makes history self-describing and lets the movement-consistency test assert correctness. Low cost, high audit value. |
| D8 | Actor | LLD "actor where appropriate" | `actor_user_id` (nullable FK `users`) — records who made a manual adjustment; nullable so a future OrderService/system caller may omit it. |
| D9 | Zero-delta adjustment | §11 "explicitly handled" | **Rejected** with 422 (no meaningless history row). |
| D10 | Business PIN | FR-AUTH-03 destructive actions = delete product / refund / payout | Stock adjustment is **not** a listed sensitive action → **no PIN** (§18). |
| D11 | RBAC | Phase-3 catalog matrix | Mutations (create/adjust/threshold) → OWNER/EMPLOYEE; reads → any authenticated principal; **ADMIN denied** mutations (matches the approved Phase-3 policy). |
| D12 | Idempotency | §21 | No idempotency key for MVP manual adjustments; retry safety is a caller/UI concern. Documented, not implemented. |
| D13 | Quantity type | §11 | Integer only; no floating point. |

## 3. Final schema

**`inventory`**
- `id` BIGSERIAL PK
- `business_id` BIGINT NOT NULL → `business(id)` ON DELETE CASCADE
- `product_id` BIGINT NOT NULL → `product(id)` ON DELETE CASCADE, **UNIQUE**
- `quantity` INT NOT NULL DEFAULT 0 — `CHECK (quantity >= 0)`
- `low_stock_threshold` INT NOT NULL DEFAULT 0 — `CHECK (low_stock_threshold >= 0)`
- `created_at`, `updated_at` (TimestampMixin)
- Index `ix_inventory_business_id (business_id)`; unique `uq_inventory_product_id (product_id)`

**`stock_movement`** (append-only, immutable)
- `id` BIGSERIAL PK
- `business_id` BIGINT NOT NULL → `business(id)` ON DELETE CASCADE
- `inventory_id` BIGINT NOT NULL → `inventory(id)` ON DELETE CASCADE
- `product_id` BIGINT NOT NULL → `product(id)` ON DELETE CASCADE (denormalized, matches LLD `append(productId, …)` and supports per-product history)
- `delta` INT NOT NULL — `CHECK (delta <> 0)`
- `resulting_quantity` INT NOT NULL — `CHECK (resulting_quantity >= 0)`
- `movement_type` VARCHAR(20) NOT NULL — `RESTOCK|SALE|MANUAL_ADJUSTMENT|DAMAGE`
- `actor_user_id` BIGINT NULL → `users(id)` ON DELETE SET NULL
- `created_at`, `updated_at` (TimestampMixin; never updated — immutable)
- Indexes `ix_stock_movement_business_inventory (business_id, inventory_id)`, `ix_stock_movement_business_id (business_id)`

## 4. Single write authority & concurrency

`InventoryService.adjust_stock()` is the ONLY path that mutates `quantity`. It:
1. selects the inventory row `... FOR UPDATE` (real PostgreSQL row lock) scoped by
   `business_id`; 2. reads quantity under the lock; 3. computes the result;
4. rejects if `< 0` (`InsufficientStockError`, no partial write, no movement);
5. writes quantity; 6. inserts one immutable `StockMovement`; 7. commits;
8. **after commit**, publishes `LowStock` if `quantity <= low_stock_threshold`.

**Event/commit ordering (§14):** the low-stock event is published *after* a
successful commit, so an event is never emitted for a rolled-back change. The
Phase-1 `EventBus` is synchronous in-process; the only residual limitation is that
a process crash in the window between commit and publish would drop that event
(no transactional outbox). This is acceptable for the MVP and documented here
rather than adding broker infrastructure (§13, §14).

## 5. Future integration (no code this phase)

`adjust_stock(business_id, inventory_id, *, delta, movement_type, actor_user_id)`
and the convenience `adjust_stock_by_product(business_id, product_id, …)` are the
clean application methods a future `OrderService` (SALE) or Conversation handler
("Add 20 notebooks") will call. Neither may touch `inventory.quantity` directly.
Inventory depends on the Catalog `Product` (read-only ownership check); Catalog
stays independent of Inventory (no circular dependency).
