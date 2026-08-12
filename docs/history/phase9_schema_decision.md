# Phase 9 — Invoice Management: Schema Consistency & Decision Report

Reviewed against: SRS §4.9 (FR-INVC-01..03) & AC-06, SDD §5/§7.9, LLD §2.2/§7.4,
PDD §7.1(#9)/§7.2, and the Phase 1–8 code (Order/OrderItem snapshots, Payment,
Money, ObjectStorage, `pdf` extra = reportlab).

## 1. What the design says

- **FR-INVC-01**: generate a **PDF invoice with a unique invoice number, line items
  and tax** (High). **FR-INVC-02**: share over WhatsApp (High) — **out of Phase-9
  scope** (WhatsApp unimplemented; deferred). **FR-INVC-03**: downloadable from the
  dashboard (Medium).
- **LLD §7.4 numbering** (gap-free per business per year):
  `seq = counterRepo.incrementFor(businessId, year())` (atomic) → `INV-{year}-{seq:04d}`.
- **LLD §2.2**: an Order **owns exactly one Invoice**.
- **SDD §7.9**: `InvoiceService` (PDF composition, numbering, tax) + `PdfRenderer`;
  on payment/confirmation → allocate number → render line items + tax → store PDF in
  object storage → (share over WhatsApp / downloadable). Data touched: Invoice,
  Order, OrderItem. Patterns: Repository, template rendering, triggered by payment.
- **PDD §7.2 (deferred)**: refunds/partial payments — so invoices are single, full,
  post-payment documents; no credit notes.

## 2. Decisions

| # | Topic | Decision |
|---|-------|----------|
| D1 | Eligibility (§6) | An invoice may be generated only for an order that has reached **PAID or a later fulfillment state** (PAID, PACKED, SHIPPED, DELIVERED, COMPLETED) — i.e. a successful payment exists. CREATED/CONFIRMED/CANCELLED are rejected. Follows SDD "triggered by the payment event." |
| D2 | COD semantics (§8) | A COD order reaches PAID **only after `confirm-cod`** (Phase 8 = merchant attests cash received). Since eligibility requires PAID, an invoice is never generated before COD collection, so `payment_status` on the invoice is always **PAID** and faithfully reflects collected money. "COD payment record exists" ≠ paid is handled by requiring order PAID, not merely a payment row. |
| D3 | One invoice per order (§17) | **DB unique constraint on `order_id`**. Duplicate generation is **idempotent**: a repeat request returns the existing invoice (concurrent race → unique violation caught → return existing). Realizes LLD "owns exactly one Invoice." |
| D4 | Numbering (§16) | `INV-{YYYY}-{NNNN}`, **sequential, gap-free, per business per year**, via an `invoice_counter(business_id, year, next_seq)` table incremented with an atomic Postgres UPSERT (`INSERT … ON CONFLICT DO UPDATE SET next_seq = next_seq+1 RETURNING`). The counter increment and invoice insert share **one transaction**, so a failed insert rolls back the increment (no gap). The conflict row-lock serializes concurrent generation (race-safe). Unique `(business_id, invoice_number)` is the backstop. |
| D5 | Immutability (§10) | An invoice is **ISSUED and immutable**: no PATCH/PUT/edit/cancel API (not in the approved requirements). All financial/customer/line fields are stored snapshots; nothing recomputes from live Product/Customer/Order. |
| D6 | State machine (§9) | Single status **`ISSUED`** (invoices are created issued and never mutated). No DRAFT (created directly) and no CANCELLED (cancellation/credit-notes not required; refunds deferred). |
| D7 | Financial snapshot (§11) | Snapshot `subtotal_amt` (= order.total − order.tax), `tax_amt`, `total_amt`, `currency` — all Decimal, copied from the **authoritative Order** at issuance (client never supplies them). |
| D8 | Discount (§12) | Reaffirm the Phase-7 decision: the approved Order model has **no discount column**; the invoice faithfully reflects Order totals and **does not invent a discount**. No compatibility change needed. |
| D9 | Tax (§13) | The Order stores the final `tax_amt` (not a rate). The invoice snapshots that **tax amount** and totals; it never recomputes historical tax from current config. |
| D10 | Customer/business snapshot (§14) | Snapshot `customer_name`, `customer_phone` (read with `include_deleted=True` so a later soft-delete/edit can't alter the invoice) and `business_name`. Order has no address link (Phase 7), so no address snapshot. |
| D11 | Line items (§15) | `invoice_item` rows copy the existing **OrderItem snapshots** (`product_name`, `unit_price`, `quantity`, `line_total`). Product is never re-read. |
| D12 | Payment info (§7) | Snapshot `payment_method` (ONLINE/COD), `payment_reference` (provider payment id) and `payment_status` (PAID) by **reading** the successful Payment. Invoice never creates/verifies/mutates payment. |
| D13 | PDF (§18–20, §27) | Rendered with **reportlab** (the declared `pdf` extra) from the immutable invoice snapshot only. Transaction strategy: create+commit the invoice first, **then** render+store the PDF (a second commit) — the slow render never holds the invoice transaction. On PDF failure the invoice stays ISSUED with `pdf_storage_key` NULL (recoverable); no fake reference. The download endpoint regenerates deterministically from the snapshot if the stored PDF is missing. |
| D14 | Storage (§19) | Via the existing `ObjectStorage` protocol (never the S3 SDK), key `invoices/{business_id}/{invoice_id}/invoice.pdf`. Only the key/URL is stored in the DB. |
| D15 | Generation trigger | **Explicit** `POST /api/invoices {order_id}` (dashboard). Auto-generation on the Phase-8 `PaymentSucceeded` event is deferred wiring (keeps Payment frozen; no coupling). |
| D16 | RBAC (§24) | Generate → OWNER/EMPLOYEE; read/list/pdf → any authenticated principal; **ADMIN denied** generation. No Business PIN. |

## 3. Schemas

**`invoice`**: `id` PK; `business_id`→business CASCADE; `order_id`→orders RESTRICT
**UNIQUE**; `invoice_number` VARCHAR(32); `status` VARCHAR(20) (ISSUED); `issued_at`
TIMESTAMPTZ; `currency` VARCHAR(3); `subtotal_amt`/`tax_amt`/`total_amt`
NUMERIC(12,2) (`CHECK total_amt>=0`); `customer_name`/`customer_phone`/`business_name`
snapshots; `payment_method`, `payment_reference`, `payment_status`; `pdf_storage_key`
VARCHAR(512) NULL, `pdf_url` VARCHAR(1024) NULL; timestamps. Unique
`(business_id, invoice_number)`; indexes `(business_id)`, `(business_id, status)`.

**`invoice_item`**: `id` PK; `business_id`→business CASCADE; `invoice_id`→invoice
CASCADE; `product_id`→product SET NULL (reference); `product_name` VARCHAR(200);
`unit_price` NUMERIC(12,2); `quantity` INT (`CHECK>0`); `line_total` NUMERIC(12,2).
Index `(business_id, invoice_id)`.

**`invoice_counter`**: `business_id`→business CASCADE + `year` INT → PK
`(business_id, year)`; `next_seq` INT. Atomic per-business-per-year sequence source.

## 4. API (§22)

`POST /api/invoices` (generate, OWNER/EMPLOYEE), `GET /api/invoices` (list),
`GET /api/invoices/{id}` (detail + items), `GET /api/invoices/{id}/pdf` (download).
No PUT/PATCH; no client-supplied financial values.

## 5. Transaction & consistency (§27)

TX1: validate order eligible + not already invoiced → allocate number (counter
upsert) → insert invoice + items → **commit**. TX2 (separate): render PDF from the
snapshot → store → update `pdf_storage_key/url` → **commit**. A PDF failure leaves a
valid ISSUED invoice with the PDF pending; the download endpoint regenerates it.
Concurrency verified by real-PostgreSQL tests (one invoice per order; distinct
sequential numbers under concurrent generation).
