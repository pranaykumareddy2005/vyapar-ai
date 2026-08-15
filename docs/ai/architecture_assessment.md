# AI Layer — Architecture Assessment (pre-change inspection)

_Prepared before any modification, per the engineering brief. Records the current
state of the AI layer, what exists, what is mocked, and exactly what the Ollama +
multilingual work must add without disturbing the approved domain architecture._

## 1. What AI functionality already exists

| Area | Module | Status |
|------|--------|--------|
| Conversational intent parsing | `app/conversation/` | Implemented. Text → `ResolvedIntent` → handler registry → domain services → deterministic English replies. |
| AI Catalog Generator (vision) | `app/catalogai/` | Implemented. Image → `AiDraftPayload` → persisted draft → merchant review → approval → `CatalogService.create_product`. |

Supported conversational intents: `SEARCH_PRODUCT`, `GET_STOCK`, `ADJUST_STOCK`,
plus the control intents `UNSUPPORTED` and `CLARIFICATION_REQUIRED`.

## 2. AI provider abstractions already present

Two independent, vendor-neutral `Protocol`s — the domain never imports an SDK:

- `app.conversation.provider.ConversationAiProvider` — `resolve(text) -> ResolvedIntent`.
- `app.catalogai.provider.AiProvider` — `describe(image, content_type) -> AiDraftPayload`.

Each has a full infrastructure exception hierarchy (`*Timeout`, `*Unavailable`,
`*RateLimited`, `*ConfigError`, `*InvalidResponse`) that the services turn into
controlled user-facing replies / durable failure states.

## 3. What is a mock vs. vendor-specific

- **Mock (dev/test):** `MockConversationAiProvider` (deterministic English keyword
  engine) and `MockAiProvider` (fixed catalog draft).
- **Vendor (Gemini):** `app/conversation/adapters/gemini.py`,
  `app/catalogai/adapters/gemini.py`. HTTP-mock tested; **never run live** (no key).
- Composition root `app/providers.py` selects by `settings.ai_provider ∈ {mock, gemini}`;
  mock is rejected in production (fails loudly).

## 4. What must be added for Ollama

- A new `ai_provider = "ollama"` option, wired in the **composition root only**.
- `OllamaConversationAdapter` implementing `ConversationAiProvider`.
- `OllamaAdapter` (vision) implementing `AiProvider`.
- Configurable base URL + per-workload model names. **No** Ollama import in any
  domain service (`Catalog/Inventory/Order/Payment/Invoice/Conversation` logic).

## 5. What must be added for multilingual support

- A `language` field on `ResolvedIntent` (currently absent).
- Deterministic script-based language detection (EN / Telugu / Hindi) used to pick
  the **response** language — independent of the model, so it cannot be spoofed.
- Language-aware deterministic response templates (business values still come only
  from the domain services; the AI never invents numbers).
- Ollama prompts that instruct multilingual understanding (EN/TE/HI, romanized and
  code-mixed) while still emitting the **same** language-neutral structured intent.

## 6. Business operations already supported (unchanged, authoritative)

`CatalogService`, `InventoryService`, `OrderService`, `PaymentService`,
`InvoiceService`, `NotificationService`, analytics/dashboard — each remains the
sole authority for its writes. The conversation pipeline only reaches
`CatalogService` (read) and `InventoryService` (`adjust_stock_by_product`).

## 7. Conversational operations currently supported / must remain unsupported

- **Supported:** product search, stock query, stock adjust (restock/sale/damage/manual).
- **Must remain UNSUPPORTED via the conversation channel:** orders, customers,
  payments, invoices, refunds, notifications, analytics. These are routed to the
  `UNSUPPORTED` intent and never mutate. This boundary is preserved.

## 8. Invariants that must not change

- AI is data, never authority. `business_id`/`actor_user_id` come only from the JWT
  principal; `ResolvedIntent` carries no tenant/id (`extra="ignore"` drops any).
- Low-confidence actionable intents never mutate (confidence gate).
- Domain services own all writes and transaction boundaries.
- Providers are chosen explicitly; no silent fallback to mock in production.
</content>
</invoke>
