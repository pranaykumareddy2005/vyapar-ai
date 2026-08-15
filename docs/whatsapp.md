# WhatsApp / Meta Cloud API Integration

WhatsApp is a **communication channel**, not a business layer. Inbound messages
are normalized to the vendor-neutral `IncomingMessage` and run through the exact
same pipeline the dashboard uses; outbound replies go back through the
`MessagingProvider` boundary. No Meta payload shape leaks past `app/whatsapp/`.

```
Customer WhatsApp
      │
      ▼
Meta WhatsApp Cloud API
      │  POST /webhooks/whatsapp   (signature-verified)
      ▼
MetaWhatsAppParser ──► ParsedWhatsAppMessage      (normalization boundary)
      │
      ▼
resolve tenant (phone_number_id → business_id)    (trusted, server-side)
      │
      ▼
idempotency claim (Postgres unique)               (dedupe redeliveries)
      │
      ▼
CustomerService.get_or_create_by_phone            (sender → customer)
      │
      ▼
ConversationService  ─►  Ollama/AI  ─►  ResolvedIntent  ─►  confidence gate
      │
      ▼
CATALOGUE (CatalogService)  ─►  InventoryService   (authoritative product/stock)
      │
      ▼
deterministic reply (per-language template)
      │
      ▼
MetaWhatsAppProvider ──► Meta Cloud API ──► Customer WhatsApp
```

**Principle:** AI is intelligence; domain services are authority; the Catalogue is
the authoritative product layer. The AI never invents a product, price, stock,
`business_id`, or id — it produces a `product_query` that `CatalogService` resolves
within the server-resolved tenant.

## Components (`app/whatsapp/`)

| File | Responsibility |
|------|----------------|
| `provider.py` | `MetaWhatsAppProvider` — outbound text/image/document + media upload/download over the Graph API. Implements `MessagingProvider`. No business logic. |
| `parser.py` | `MetaWhatsAppParser` — Meta webhook JSON → `ParsedWhatsAppMessage`. Defensive; never raises on bad shapes. |
| `signature.py` | `X-Hub-Signature-256` HMAC verification (constant-time). |
| `models.py` / `repository.py` | `ProcessedWebhookEvent` dedup table + atomic `try_claim`. |
| `service.py` | `WhatsAppWebhookService` — resolve tenant → dedupe → customer → conversation. |
| `router.py` | `GET`/`POST /webhooks/whatsapp`. |
| `dependencies.py` | DI wiring (single request-scoped session). |

## Environment variables

Placeholders live in `.env.example`; real values go in your local `.env` only
(gitignored). **Never commit the access token.**

```env
MESSAGING_PROVIDER=meta          # mock | meta   (alias: whatsapp)
WA_VERIFY_TOKEN=                 # you also enter this in the Meta webhook config
WA_API_TOKEN=                    # SECRET Graph API access token
WA_PHONE_NUMBER_ID=              # Meta asset id of the WhatsApp line (not the number)
WA_BUSINESS_ACCOUNT_ID=          # WABA id (identifier)
WA_APP_SECRET=                   # SECRET; enables X-Hub-Signature-256 checks (empty => skipped)
WA_API_BASE=https://graph.facebook.com
WA_API_VERSION=v21.0
WA_REQUEST_TIMEOUT_SECONDS=30.0
```

`WA_PHONE_NUMBER_ID` is the numeric Meta asset id (e.g. `1324744104046168`), which
is different from the E.164 phone number. `WA_BUSINESS_ACCOUNT_ID` is the WABA id
(e.g. `977808445268067`).

## Business ↔ WhatsApp line mapping

Multi-tenant: an inbound message resolves to a business by matching the Meta
`phone_number_id` (from `value.metadata.phone_number_id`) to
`business.whatsapp_phone_number_id`. This is **trusted server-side configuration**,
never taken from message content. Link it with
`BusinessService.link_whatsapp_phone_number_id(business_id, phone_number_id)`
(partial-unique; a `phone_number_id` maps to at most one business).

## Meta setup

1. In the Meta App dashboard, add the **WhatsApp** product; note the **Phone number
   ID** and **WhatsApp Business Account ID**; generate an **access token**.
2. Put the token in your local `.env` as `WA_API_TOKEN` (never commit it).
3. Map the line: set `business.whatsapp_phone_number_id` for the dev business.
4. Configure the webhook (below) and subscribe to the **messages** field.

## Webhook configuration

- **Callback URL:** `https://<public-host>/webhooks/whatsapp`
- **Verify token:** the value of `WA_VERIFY_TOKEN`
- **Signature:** set `WA_APP_SECRET` to your app secret to enforce
  `X-Hub-Signature-256` on every POST (recommended for production).

On save, Meta issues a `GET` with `hub.mode=subscribe`, `hub.verify_token`, and
`hub.challenge`; the endpoint echoes the challenge only when the token matches.

## Local development & real testing

Meta must reach a **public HTTPS** URL; it cannot call `localhost`. For a live
inbound test, expose the local app with a temporary tunnel:

```bash
# start the stack (app on :8080)
docker compose up -d

# expose it (either tool)
ngrok http 8080
# or: cloudflared tunnel --url http://localhost:8080
```

Register `https://<tunnel-domain>/webhooks/whatsapp` as the callback URL with your
`WA_VERIFY_TOKEN`, subscribe to **messages**, then send a WhatsApp message to the
business number and watch it round-trip. Keep the tunnel temporary.

Outbound sends work from any machine (no tunnel needed).

## Deduplication & idempotency

Meta delivers **at least once**. Every provider message id (`wamid…`) is claimed
once via a Postgres unique index (`processed_webhook_event`). A duplicate delivery
fails to claim and is skipped, so it never:

- adjusts inventory twice,
- creates a duplicate customer,
- sends a duplicate reply.

The dedup claim, the customer upsert, and the conversation's catalogue/inventory
work share **one request-scoped transaction**, so they commit atomically.

## Retries

- **Outbound sends** are single-attempt (no automatic retry) — matching the other
  adapters (Razorpay/Gemini/Ollama). A failed send surfaces a typed error; the
  conversation reply is best-effort and never blocks domain state.
- **Inbound mutations are never blindly retried.** If processing a message fails,
  the transaction rolls back (including the dedup claim) so Meta's redelivery can
  reprocess safely; a message that produced a controlled reply is marked processed
  so it is not answered twice.

## Media handling

- Inbound **images** are acknowledged with a graceful reply but are **not**
  auto-converted into catalogue drafts: a WhatsApp sender carries no authenticated
  merchant identity/RBAC, so image→catalogue creation stays on the authenticated
  `/api/catalog-ai/drafts` endpoint (merchant review + merchant-set price remain
  mandatory). `MetaWhatsAppProvider.download_media` is implemented for when an
  owner-phone mapping is added.
- Outbound **documents** (e.g. invoice PDFs from `InvoiceService.get_pdf`) are sent
  by uploading bytes to Meta (`upload_media`) then sending a `document` message.

## Security

- **Webhook auth:** verify token (GET) + optional `X-Hub-Signature-256` app-secret
  signature (POST). No JWT (Meta cannot present one); the route has no auth
  dependency by design.
- **Tenant isolation:** `business_id` comes only from the trusted `phone_number_id`
  mapping. Message content (and the AI) cannot select or switch tenants.
- **AI containment:** `ResolvedIntent` carries no `business_id`/`product_id`
  (`extra="ignore"`); no SQL, no function selection, no direct DB mutation. Multi-
  lingual prompt-injection is classified UNSUPPORTED and mutates nothing.
- **Secrets:** the access token lives only in the `Authorization` header on the
  HTTP client and never appears in logs, errors, or responses.

## Deployment requirements

- Public HTTPS endpoint for the webhook (TLS terminated by your platform/tunnel).
- `WA_*` secrets provided via environment (not committed).
- Postgres (dedup + domain), Redis, object storage as for the rest of the app.
- Latency note: end-to-end response time is dominated by AI inference (Ollama
  ~6–7 s/request on a modest laptop GPU). Processing is synchronous; there is no
  premature queue/cache.

## Known limitations

- **Live inbound requires a public tunnel/host** (Meta cannot reach localhost).
- WhatsApp image → catalogue draft is intentionally **not** enabled (no merchant
  RBAC over the channel).
- Business-initiated messages outside the 24-hour session window require Meta-
  approved templates; `OutgoingMessage.template_name` is supported but template
  registration/management is out of scope.
- No WhatsApp-initiated payment flow (payment stays on the existing
  PaymentService/verification path — "payment done" text can never mark an order
  paid).

## Tests

- `tests/unit/test_whatsapp_parser.py`, `…_provider.py`, `…_signature.py`
- `tests/integration/test_whatsapp_webhook.py` — verification, catalogue-first
  resolution, tenant isolation, idempotency, security, multilingual channel.
