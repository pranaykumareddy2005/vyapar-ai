# Vyapar AI — Project Overview: What It Is, What's Done, What Remains

_Last updated: 2026-08-14. This is a plain-language map of the whole project and an
honest status of every part. For deep dives see the linked docs._

---

## 1. What this project is

**Vyapar AI** is a multi-tenant backend for small businesses ("dukaans") to run
their daily operations — catalog, inventory, customers, orders, payments,
invoices — with an **AI assistance layer** on top:

1. **Catalog AI** — turn a product image into a structured *draft* (name,
   description, category, SKU, tags) that a human reviews and approves.
2. **Conversational AI** — a merchant sends a natural-language message ("how many
   notebooks are left?", "add 20 notebooks") and the system understands it,
   performs the real inventory operation, and replies — now in **English, Telugu,
   or Hindi**.

It is a **Python / FastAPI modular monolith**: PostgreSQL + SQLAlchemy + Alembic,
Redis (auth only), Docker Compose, JWT auth with RBAC, strict tenant isolation,
and provider abstractions for every external dependency.

**The golden rule:** _AI understands language and proposes structured data;
validated backend services remain the sole authority for executing business
operations._ The AI never writes to the database, never sets the tenant, never
invents a number.

---

## 2. The architecture in one picture

```
User (WhatsApp-style message / API)
      │
      ▼
ConversationService ──▶ AiProvider ──▶ Ollama / Gemini / Mock adapter
      │                                     │
      │                            Structured Intent (JSON)
      │                                     │
      ▼                                     ▼
Validation  ◀───────────────────────  strict Pydantic re-validation
(confidence gate, tenant from JWT, ids stripped)
      │
      ▼
Domain Service (the authority)
  Catalog · Inventory · Order · Payment · Invoice
      │
      ▼
Deterministic reply, in the user's language
```

Everything below the "Validation" line is deterministic and testable. The AI only
influences *which* operation and *which* language — never the values.

---

## 3. What was already built (the business core) — DONE

These ten modules existed before this AI work and are unchanged in behaviour:

| Module | What it does | Status |
|--------|--------------|--------|
| Auth + Business | JWT, refresh rotation, RBAC (OWNER/EMPLOYEE/ADMIN), Business PIN, tenant isolation | Done |
| Catalog | Categories, products, images, soft-delete | Done |
| Catalog AI | Image → draft → merchant review → approval → product | Done |
| Inventory | Stock + immutable movement log, row-locked single-writer, low-stock events | Done |
| Conversational AI | Intent pipeline (search / stock / adjust) | Done (extended here) |
| Customers + Orders | Guarded order state machine, atomic inventory sync | Done |
| Payments | State machine, mock + Razorpay adapter, DB-enforced idempotency | Done |
| Invoices | Immutable numbered PDF from a paid order | Done |
| Notifications | In-app notifications from domain events | Done |
| Analytics + Dashboard | Read-only SQL aggregates + composed KPI view | Done |

---

## 4. What THIS work added (the AI layer) — DONE

The goal was: **accurate, multilingual, locally-runnable AI**, without breaking any
of the above. Delivered:

### 4.1 Local inference via Ollama (provider-agnostic)
- New `AI_PROVIDER=ollama` option, wired **only** in the composition root
  (`app/providers.py`). No domain service imports Ollama.
- `OllamaConversationAdapter` (text → intent) and `OllamaAdapter` (image → draft),
  both talking HTTP to a local Ollama server with **structured JSON output** and
  strict re-validation. See `docs/ai/ollama.md`.
- Configurable per-workload models (`OLLAMA_CONVERSATION_MODEL`,
  `OLLAMA_CATALOG_MODEL`, `OLLAMA_EMBEDDING_MODEL`) — no model name is hard-coded.

### 4.2 Multilingual understanding + responses (EN / Telugu / Hindi)
- The model understands native script, romanized, and code-mixed input and maps
  them all to the **same** language-neutral intent.
- Reply language is chosen **deterministically from the user's own text** (Unicode
  script detection), so it can't be spoofed, and replies use per-language
  templates into which the domain service's real values are interpolated. The AI
  never phrases the number. See `docs/ai/multilingual.md`.
- English output is byte-identical to before — existing behaviour preserved.

### 4.3 Accuracy, safety, and evaluation
- Confidence gate unchanged: low-confidence actionable intents never mutate, in
  any language.
- A **31-case multilingual evaluation suite** (`evals/`) measures model accuracy
  separately from business-operation correctness. Run with
  `python -m evals.run_eval --provider ollama`.
- **Measured live** on local `qwen2.5:7b` (see `docs/ai/evaluation_report.md`):

  | Metric | Result |
  |--------|--------|
  | Intent accuracy | 93.5% |
  | Quantity / Direction extraction | 100% / 100% |
  | Product resolution | 95.2% |
  | Language detection | 100% |
  | Unsupported-request detection | 100% |
  | Prompt-injection rejection (model layer) | 100% |
  | Provider errors | 0 / 31 |
  | Avg latency | ~6.3 s (RTX 3050, 6 GB) |

### 4.4 Model selection (hardware-aware)
Detected: 16 CPU cores, 15.3 GB RAM, RTX 3050 **6 GB VRAM**. Chosen to fit that:
- Conversation: **`qwen2.5:7b`** (4.7 GB, strong multilingual + JSON). Lighter
  `qwen2.5:3b-instruct` / `llama3.2:3b` available for lower latency.
- Catalog vision: **`qwen2.5vl:3b`**.
- Embeddings: **`mxbai-embed-large`** (scaffolding only). Full report:
  `docs/ai/model_selection.md`.

### 4.5 Tooling & docs
- Optional `ollama` Docker Compose service behind a profile (not forced into the
  app image).
- `.env.example`, README, and four new `docs/ai/*.md` files updated.

---

## 5. Quality gates — ALL PASS (actually executed)

| Gate | Result |
|------|--------|
| `ruff check` | Pass |
| `ruff format --check` | Pass (198 files) |
| `mypy --strict` (app + evals) | Pass (121 + 4 files) |
| `bandit` | Pass (0 issues) |
| `pytest` (full suite) | **434 passed** (was 372; +62 new) |
| Coverage | 90% |
| Docker build | Pass |
| Docker Compose config (incl. ollama profile) | Valid |
| Live Ollama connectivity + model eval | Pass (real inference) |

No DB schema change was introduced (the `language` field is Pydantic-only), so
Alembic is untouched and still single-head.

---

## 6. What is honestly NOT done / provider-dependent

Stated plainly, per the engineering brief:

- **WhatsApp / Meta integration is NOT implemented.** The conversational pipeline
  runs through a `MessagingProvider` boundary with a **mock** provider only;
  selecting `whatsapp` raises `NotImplementedError`. "WhatsApp-based" describes the
  intended channel, not a shipped Meta integration.
- **Gemini and Razorpay adapters are mock-tested only** — never run against live
  credentials/gateways in this environment.
- **Ollama vision (catalog) path and the embedding client** are implemented and
  unit-tested against mocked HTTP, but **not benchmarked live**. Only the
  conversation path was measured live.
- **Semantic product search is scaffolding, not wired.** The embedding client
  exists; no vector store was added (deliberately — it would be infrastructure for
  appearance). The keyword resolver via `CatalogService` is what runs today.
- **Event delivery is in-process** (no outbox/broker); a crash between commit and
  the notification write loses that one notification.

---

## 7. Recommended next steps

1. **Real WhatsApp Cloud API adapter** implementing `MessagingProvider` (webhook
   verify + inbound parse + outbound send), so the conversation layer reaches real
   users. This is the single biggest gap for the "WhatsApp commerce" vision.
2. **Live-verify Gemini and Razorpay** with real credentials in a staging secret
   store; record the results.
3. **Benchmark the Ollama vision catalog path** on real product photos; tune the
   vision model / prompt.
4. **Wire multilingual semantic search** using the embedding client + a pgvector
   column (tenant-scoped), upgrading the embedding model to `bge-m3`.
5. **Latency**: offer the 3B conversation model by default on low-VRAM hosts;
   consider response streaming for the chat endpoint.
6. **Durable events**: add a transactional outbox if notification delivery must be
   guaranteed.

---

## 8. How to run it

```bash
# 1. Infra
docker compose up -d db redis minio

# 2. App (host)
pip install -e ".[dev,storage,pdf]"
alembic upgrade head
uvicorn app.main:app --reload

# 3. Local AI (host Ollama recommended)
ollama pull qwen2.5:7b
#   .env: AI_PROVIDER=ollama, OLLAMA_BASE_URL=http://localhost:11434

# 4. Verify AI quality
python -m evals.run_eval --provider ollama   # writes docs/ai/evaluation_report.md
```

See `docs/ai/ollama.md` for the Docker-based Ollama alternative and
`docs/ai/architecture_assessment.md` for the pre-change inspection notes.
</content>
