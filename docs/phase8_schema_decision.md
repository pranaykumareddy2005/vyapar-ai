# Phase 8 — Payment Management: Schema Consistency & Decision Report

Reviewed against: SRS §4.8 (FR-PAY-01..04) & UC-05, SDD §5 (API), §7.8, §9,
LLD §2.2/§2.4/§5.1, Impl Guide §5.6, PDD §7.1(#8)/§7.2, and the Phase 1–7 code
(Order state machine + the temporary `pay` transition, InventoryService locking,
Money, EventBus).

## 1. What the design says

- **FR-PAY-01..04**: generate a Razorpay-sandbox **payment link** for online
  payment; support **COD**; **update order status on payment confirmation from the
  gateway**; expose payment behind an **adapter interface** for future providers.
- **LLD §2.4**: `PaymentMethodStrategy` (OnlineStrategy = gateway link, CodStrategy =
  defer to delivery); `PaymentGateway` abstracts the provider with `RazorpayAdapter`
  as the only concrete MVP impl; `PaymentService.pay(order) -> Payment` selects the
  strategy; `PaymentGateway.verify(sig)` validates a webhook signature.
- **LLD §2.2 / §5.1**: an Order **owns exactly one Payment**; `confirmed --pay/COD-->
  paid` on "Payment success or COD accepted."
- **SDD §5**: `POST /api/payments/link` (create link), `POST /api/webhook/razorpay`
  (signature-verified callback).
- **PDD §7.2 (deferred)**: "Multiple payment gateways / **refunds** / **partial
  payments**" are explicitly **out of MVP scope** — the adapter seam is designed
  for, not built.
- The SDD entity dictionary lists 10 tables and does **not** enumerate Payment
  fields → the Payment schema is designed here and justified (§10 of the prompt).

## 2. Decisions

| # | Topic | Decision |
|---|-------|----------|
| D1 | Provider abstraction | Vendor-neutral **`PaymentProvider`** protocol (the LLD "PaymentGateway"): `create_payment(...)` (initiate/link) and `verify_payment(...)` (fetch/verify facts). `MockPaymentProvider` + `RazorpayAdapter` realize it. Razorpay SDK/types never leak past the adapter. |
| D2 | Method strategy | `PaymentMethod` = `ONLINE` \| `COD` (LLD §2.4). ONLINE goes through the provider; COD is confirmed by an authorized merchant action ("cash received"). Both reach SUCCESS→Order PAID through the same `PaymentService`/`OrderService` boundary. Implemented as service branching + a provider seam (the two axes the LLD describes), not separate strategy classes — keeps the interface minimal (§7). |
| D3 | One successful payment per order | An Order may have **multiple payment attempts (rows)** but **at most one SUCCESS**, enforced by a **partial unique index** `(order_id) WHERE status='SUCCESS'`. This realizes LLD "owns exactly one Payment" (= one *successful* payment) and PDD "no partial payments," and makes competing successes (§21/§26 B) impossible at the DB layer. |
| D4 | Idempotency | Three DB-enforced invariants (not `if exists`): (a) one SUCCESS per order (D3); (b) `(business_id, provider_payment_id) WHERE NOT NULL` unique → a provider payment id can back only one payment, blocking cross-order replay (§17) and duplicate callbacks (§20); (c) `(business_id, idempotency_key) WHERE NOT NULL` unique → idempotent initiation (§19). Verification also **row-locks the payment `FOR UPDATE`** so concurrent verifies of the same payment serialize (§26 A). |
| D5 | Payment ≠ Order state | `PaymentService` never writes Order ORM status. It reaches PAID **only** via `OrderService.transition(PAY)` (§2/§12). Payment never touches inventory (§24). |
| D6 | Phase-7 `pay` transition | The Phase-7 order-transition **API** currently exposes `PAY`, letting a client reach PAID with no verified payment — this conflicts with §2/§14. **Smallest fix:** the order transition **router** now rejects a client `PAY` event (409, "use the payment API"); `OrderService.transition` and the transition table are **unchanged**, so `PaymentService` still drives `PAY` internally. This touches one Phase-7 file (`app/order/router.py`) and requires updating one Phase-7 test that drove PAY over HTTP (see completion report). |
| D7 | Order eligibility | Payment is allowed only for an order in **CONFIRMED** (stock already reserved on confirm). CREATED/CANCELLED/COMPLETED/PAID are rejected; an order already SUCCESS-paid → idempotent/conflict. No new order states (§13). |
| D8 | Amount / currency | Expected amount = the server-side **`order.total_amt`** at initiation (client amount never trusted, §15). Currency from **config** (`default_currency`, INR), never client (§16). On verify, the provider's reported amount **and** currency **and** order reference must match the payment record or it becomes FAILED (§15/§17). |
| D9 | Payment state machine | `CREATED → PENDING → SUCCESS/FAILED/CANCELLED`; direct `CREATED → SUCCESS/FAILED/CANCELLED` allowed. SUCCESS/FAILED/CANCELLED are **terminal**. Re-verifying SUCCESS = **idempotent no-op**. **No SUCCESS→FAILED** (a late failure callback can't undo success). **No FAILED→SUCCESS** — a retry is a **new** payment attempt/row (§11/§23). |
| D10 | Refunds / partial | **Deferred** (PDD §7.2). Not implemented (§28). |
| D11 | Webhook | A provider-neutral verify boundary is implemented; the Razorpay adapter exposes a `verify_signature` seam. **Live Razorpay signature/webhook verification is NOT executed** (no credentials); adapter is covered via mocked HTTP transport. No WhatsApp webhook. |
| D12 | RBAC / PIN | Mutations (initiate, verify, confirm-COD) → OWNER/EMPLOYEE; reads → any authenticated principal; **ADMIN denied** mutations. No Business PIN (payment is not an FR-AUTH-03 destructive action; refunds/payout changes — which are — are out of scope). |
| D13 | Events | Add `PaymentSucceeded` / `PaymentFailed` to the Phase-1 EventBus (post-commit) for the future Notification module. No broker. |

## 3. `payment` schema

- `id` BIGSERIAL PK
- `business_id` BIGINT NOT NULL → `business(id)` CASCADE — tenant key
- `order_id` BIGINT NOT NULL → `orders(id)` RESTRICT — the order being paid
- `method` VARCHAR(20) NOT NULL — `ONLINE|COD`
- `amount` NUMERIC(12,2) NOT NULL — `CHECK (amount > 0)`, = order.total_amt
- `currency` VARCHAR(3) NOT NULL — from config
- `status` VARCHAR(20) NOT NULL — `CREATED|PENDING|SUCCESS|FAILED|CANCELLED`
- `provider` VARCHAR(50) NOT NULL — `mock|razorpay|cod`
- `provider_order_id` VARCHAR(128) NULL — gateway order/reference (link ref)
- `provider_payment_id` VARCHAR(128) NULL — gateway payment id (set on verify)
- `idempotency_key` VARCHAR(80) NULL — optional client initiation key
- `failure_code` VARCHAR(50) NULL, `failure_reason` VARCHAR(500) NULL
- `verified_at` TIMESTAMPTZ NULL
- `created_at`, `updated_at` (TimestampMixin)

Indexes / constraints: `ix_payment_business_id`, `ix_payment_business_order
(business_id, order_id)`; partial-unique `uq_payment_order_success (order_id)
WHERE status='SUCCESS'`; partial-unique `uq_payment_provider_payment_id
(business_id, provider_payment_id) WHERE provider_payment_id IS NOT NULL`;
partial-unique `uq_payment_idempotency_key (business_id, idempotency_key) WHERE
idempotency_key IS NOT NULL`; `CHECK (amount > 0)`.

## 4. Transaction strategy (verify success)

`PaymentService.verify` shares the request `Session` with `OrderService`:
1. **lock** the payment row `FOR UPDATE` (tenant-scoped); 2. if already SUCCESS →
idempotent return; if not in `{CREATED, PENDING}` → conflict; 3. load the order,
require CONFIRMED; 4. call `provider.verify_payment(...)` for typed facts;
5. validate status + amount + currency + provider references; on mismatch → set
FAILED, commit, raise; 6. set payment SUCCESS + provider ids + `verified_at`;
7. call `OrderService.transition(PAY)` — its single commit persists **both** the
payment SUCCESS and the order PAID atomically. The `(order_id) WHERE
status='SUCCESS'` unique index is the final backstop: a concurrent second success
fails that commit with an IntegrityError, which `PaymentService` maps to a
controlled conflict. No distributed transactions; existing inventory locking and
Order/Inventory behavior are untouched (PAY has no inventory effect).

## 5. Failure handling

Provider timeout/unavailable/auth/rate-limit/malformed → mapped to domain errors
(`PaymentProviderUnavailableError` 502); amount/currency/reference mismatch and
provider-reported failure → payment set FAILED (`PaymentMismatchError` 422 /
FAILED status); invalid transitions/duplicates → `ConflictError` 409. Raw provider
exceptions, credentials, and signatures are never logged or returned.
