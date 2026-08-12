# Phase 4 — AI Catalog Generator: Schema Consistency & Decision Report

Reviewed against: PDD §9.1, SRS §4.4 (FR-CATAI-01..05) & UC-02, SDD §6.2/§7.4/§5(API),
LLD §2.1/§2.3/§4.1/§6, Implementation Guide §5.4/§5.5, and the Phase 1–3 code.

## 1. What the design says

- **FR-CATAI-01..05**: accept a product photo; multimodal model drafts *title,
  description, suggested category and tags*; present the draft for review; allow
  the merchant to edit any field; **save the product only on explicit approval**.
- **SDD §7.4 / LLD §2.3 / Impl §5.5**: `CatalogAiService.generateDraft(image) → DraftDto`
  and `approve(dto) → Product`; `AiProvider.describe(image) → Draft` is a Protocol that
  `GeminiAdapter` realizes; patterns are **Adapter + Factory + human-in-the-loop gate**;
  "the draft is never persisted; only `approve()` writes a product."
- **SDD §5 (API)**: `POST /api/catalog-ai/draft`, `POST /api/catalog-ai/approve`
  (OWNER/EMPLOYEE).
- **SDD §7.4 data touched**: *Product (on approval), transient AI draft.*

## 2. Consistency findings & decisions

| # | Topic | Design | Phase-4 spec requirement | Decision |
|---|-------|--------|--------------------------|----------|
| D1 | Draft persistence | "transient" draft | §7 requires a **persisted** draft with status, timestamps, approval metadata, failure/retry | **Persist** a `catalog_ai_draft` entity. Justified: failure/retry state (§11), idempotency (§18), and tenant-isolation tests (§8) require durable state. The "transient" wording was a simpler Java MVP note; the Phase-4 spec supersedes it. **No `Product` row is ever created as the draft** (§7). |
| D2 | Endpoints | `/draft`, `/approve` | §17 lifecycle: create/retrieve/edit/approve | RESTful lifecycle under the same prefix: `POST/GET /api/catalog-ai/drafts`, `GET/PATCH /api/catalog-ai/drafts/{id}`, `POST .../{id}/approve|reject|regenerate`. Consistent with the `catalog-ai` naming in SDD §5. |
| D3 | Price | not in AI fields | §5/§15: **never infer price from an image** | AI structured schema (`AiDraftPayload`) has **no price field** and ignores any extra keys, so a price can never originate from the model. `price_amt` on the draft is **merchant-supplied only**; approval fails with 422 if unset. |
| D4 | Category | AI "suggested category" (text) | §13: don't auto-create categories; prefer existing | AI returns a category *name suggestion*. Service matches it (case-insensitive) against the business's existing categories via `CatalogService.list_categories`; on a match it sets `category_id`, otherwise leaves it null and keeps the text as a suggestion. **Never auto-creates** a category. |
| D5 | SKU | AI "suggested" | §14: AI SKU is a suggestion, not authoritative | AI value stored as `sku_suggestion`. Final SKU uniqueness is still enforced by `CatalogService.create_product` + the partial-unique DB index. AI never bypasses catalog validation. |
| D6 | Tags | AI returns tags | Product has no `tags` column | Tags are stored on the draft (review metadata) but **not** passed to `CatalogService` (the Phase-3 `Product` has no tag column; not in scope to add one). |
| D7 | Approval auth | OWNER/EMPLOYEE | §9: PIN "if required" | Approval = product creation. FR-AUTH-03 reserves the Business PIN for **destructive** actions (delete product, refund, payout). `POST /api/products` is **not** PIN-gated, so approval is **RBAC-gated (OWNER/EMPLOYEE), not PIN-gated**, for consistency. Documented, reversible. |
| D8 | Product boundary | ProductService | §2: AI calls CatalogService, never writes Product ORM | `CatalogAiService` depends on `CatalogService.create_product`; it never touches `Product`/repositories directly. Dependency direction `catalogai → catalog → db` only. |

## 3. `catalog_ai_draft` schema (final)

- `id` BIGSERIAL PK
- `business_id` BIGINT NOT NULL → `business(id)` ON DELETE CASCADE — tenant key
- `status` VARCHAR(20) NOT NULL — `PENDING|GENERATED|FAILED|APPROVED|REJECTED`
- `source_storage_key` VARCHAR(512), `source_image_url` VARCHAR(1024),
  `source_content_type` VARCHAR(100) — image in ObjectStorage, never in PG
- `name` VARCHAR(200), `description` TEXT — generated, merchant-editable
- `category_suggestion` VARCHAR(100) — raw AI text label
- `category_id` BIGINT → `category(id)` ON DELETE SET NULL — matched existing category
- `sku_suggestion` VARCHAR(64) — AI suggestion / merchant-confirmed
- `price_amt` NUMERIC(12,2) — **merchant-supplied only**, never AI
- `tags` JSON — AI tags (review metadata)
- `confidence` DOUBLE PRECISION — AI-claimed confidence (0..1)
- `ai_provider` VARCHAR(50), `ai_model` VARCHAR(100) — provenance
- `error_code` VARCHAR(50), `error_detail` TEXT — set on FAILED
- `request_key` VARCHAR(80) — optional idempotency key (unique per business when set)
- `approved_product_id` BIGINT → `product(id)` ON DELETE SET NULL
- `approved_by` BIGINT → `users(id)` ON DELETE SET NULL
- `approved_at` TIMESTAMPTZ
- `created_at`, `updated_at` (TimestampMixin)

Indexes: `ix_catalog_ai_draft_business_id (business_id)`,
`ix_catalog_ai_draft_business_status (business_id, status)`,
`uq_catalog_ai_draft_request_key (business_id, request_key)` partial-unique where
`request_key IS NOT NULL`. No vector/embedding columns (§19).

## 4. Draft lifecycle (state machine)

```
            generate (AI ok)          approve (merchant, price set)
  (start) ───────────────► GENERATED ──────────────────────────► APPROVED  (terminal)
     │                        │  ▲                                   │ creates Product via
     │ generate (AI fails)    │  │ regenerate (AI ok)                │ CatalogService only
     ▼                        ▼  │                                   │
   FAILED ◄───────────────────┘  └── reject ──► REJECTED (terminal)
     └── regenerate (AI ok) ──► GENERATED
```

Only `GENERATED → APPROVED` creates a product. Approve is idempotent: an already
APPROVED draft returns its existing product (via `approved_product_id`); a retry
after a partial failure is blocked from duplicating by the SKU unique index.
