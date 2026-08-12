# Phase 6 — Conversational AI: Architecture & Schema Decision Report

Reviewed against: PDD §9.2, SRS §4.6 (FR-CONV) & UC-03, SDD §6.1/§7.6, LLD §2.3/§7.1,
Implementation Guide §5.4/§5.7, and the Phase 1–5 code (messaging boundary,
CatalogService, InventoryService, EventBus, AiProvider).

## 1. What the design says

- **PDD §9.2 / SDD §6.1 / LLD §7.1**: free-form message → intent (type + entities
  + confidence) → route to a handler → domain service → natural-language reply.
  "Ambiguous intents produce a clarifying question rather than a guess." Confidence
  below threshold → clarify (LLD `resolveIntent` pseudocode).
- **SDD §7.6**: `AiGateway` (resolve), `IntentRouter` (route), `IntentHandler`
  realizations, `ReplyBuilder`. Patterns: Strategy/Adapter for the AI provider,
  handler-per-intent (no giant if/elif).
- **Phase-1 messaging**: `IncomingMessage` / `OutgoingMessage` / `MessagingProvider`
  (+ `MockMessagingProvider`) already exist — the vendor-neutral transport boundary.

## 2. Key decisions

| # | Topic | Decision |
|---|-------|----------|
| D1 | AI abstraction | New **`ConversationAiProvider`** protocol (`resolve(text) -> ResolvedIntent`), separate from the Catalog `AiProvider` (`describe(image)`). Per §7, unrelated AI contracts are not merged. `MockConversationAiProvider` + `GeminiConversationAdapter` realize it. |
| D2 | AI is data, not authority | `ResolvedIntent`/`IntentEntities` (Pydantic, `extra="ignore"`) carry intent, confidence, `product_query`, `quantity`, `direction`, optional `movement_type`. They contain **no `business_id` and no `product_id`** — any such key the model emits is dropped. `business_id` always comes from the authenticated principal; products are resolved by text through `CatalogService`. This structurally enforces §3/§9/§10/§33. |
| D3 | Handler registry | `dict[IntentType, IntentHandler]` (Search / GetStock / AdjustStock / Unsupported / Clarification). No if/elif chain, no generic plugin framework. |
| D4 | Single write authority | `AdjustStockHandler` calls **`InventoryService.adjust_stock_by_product`** only. The conversation layer never calculates stock, writes quantity, creates movements, or touches inventory ORM/repositories. |
| D5 | Catalog reads | Product resolution uses **`CatalogService.list_products(business_id, keyword=…)`**. The layer reads the domain objects the service returns; it never queries repositories/ORM itself and never mutates via ORM. |
| D6 | Confidence gate | Actionable intents (SEARCH/GET_STOCK/ADJUST_STOCK) with `confidence < settings.ai_confidence_threshold` (default 0.6) → clarification, **no execution**. |
| D7 | Clarification state | **Stateless.** Missing/ambiguous/low-confidence → a clarifying reply and no mutation. Multi-turn slot-filling (remembering a pending intent across messages) is **deferred** — the SDD conversational design is stateless intent routing, and no test requires continuation. **No conversation-state table.** |
| D8 | Idempotency / dedup | **No message-log table.** Duplicate-message dedup belongs to the future WhatsApp ingestion layer (which owns `message_id` and is where duplicates originate). Documented, not implemented (§17/§34). |
| D9 | Database | **No schema change, no migration** this phase (follows from D7/D8). |
| D10 | Entry points | Primary: authenticated **`POST /api/conversation/message`** (OWNER/EMPLOYEE; `business_id` from the JWT principal) — this is where the §31 auth/RBAC/tenant tests run. Plus dev-only **`POST /dev/simulate-conversation`** running the full pipeline with a channel-supplied `business_id` (simulates a WhatsApp message arriving on a business's number), satisfying §22 without Meta. The existing `/dev/simulate-message` echo endpoint is left **unchanged** (its Phase-1 regression test still passes). |
| D11 | Movement type | `AdjustStockHandler` uses `entities.movement_type` when the model supplies a valid `MovementType`, else derives deterministically: INCREASE→RESTOCK, DECREASE→SALE (DAMAGE when the message indicates damage). Never an arbitrary AI-invented type (§27). |
| D12 | Response builder | Deterministic templates in `responses.py`. The LLM never invents the final numeric/business result — replies are built from the actual `Inventory`/`Product` values returned by the services (§15/§28). |
| D13 | RBAC | Conversation endpoint requires OWNER/EMPLOYEE (it can mutate stock); ADMIN denied; unauthenticated → 401. Consistent with catalog/inventory mutation policy. |
| D14 | Latency | SRS target ≤ 3s. Measured on the mock pipeline (see completion report). No queues/workers/distributed infra introduced. |

## 3. Pipeline

```
IncomingMessage → ConversationService → ConversationAiProvider.resolve → ResolvedIntent
  → confidence gate → IntentRouter(registry) → IntentHandler → CatalogService/InventoryService
  → ResponseBuilder(template) → OutgoingMessage → MessagingProvider.send
```

## 4. Intents & outcomes

- **Intents**: `SEARCH_PRODUCT`, `GET_STOCK`, `ADJUST_STOCK`, `UNSUPPORTED`, `CLARIFICATION_REQUIRED`.
- **Outcomes** (operational metadata returned to the caller/tests, not chain-of-thought):
  `EXECUTED`, `CLARIFICATION`, `UNSUPPORTED`, `NOT_FOUND`, `REJECTED`, `ERROR`.

## 5. Prompt-injection / tenant safety (structural)

- The model can only return a constrained `ResolvedIntent`; it cannot select
  functions, emit SQL, or choose a `business_id`/`product_id` that reaches a
  service. Injection strings ("ignore previous…", "delete inventory", "run SQL",
  "use another business") are classified `UNSUPPORTED` and, even if they were not,
  could not mutate another tenant: `business_id` is from the principal and products
  resolve within that tenant only. The existing domain tenant isolation is the final
  boundary. Tested in `test_conversation_security.py`.

## 6. No new AI config

Reuses the existing `AI_PROVIDER` / `AI_MODEL` / `AI_API_KEY` /
`AI_CONFIDENCE_THRESHOLD` settings. `mock` is disallowed in production (existing
guard). Live Gemini call remains **pending** (no API key); the adapter is covered
via a mocked HTTP transport.
