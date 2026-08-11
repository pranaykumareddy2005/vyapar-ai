# Vyapar AI

Intelligent WhatsApp-Based Commerce System for MSMEs — Python/FastAPI modular monolith.

> **Status:** Phases 1–3 complete (Foundation · Auth + Business · Catalog).
> Later phases: AI Catalog, Inventory, Conversation/WhatsApp, Orders, Payments,
> Invoices, Notifications, Analytics/Dashboard.

## Stack
Python 3.12 · FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · PostgreSQL 16 · Redis 7 ·
MinIO/S3 · Docker Compose. Tooling: Ruff, mypy (strict), pytest, pytest-cov, bandit.

## Architecture
Modular monolith, package-by-feature. Layering per module:
`router (thin) → schemas (Pydantic) → service (logic + transactions) → repository → models`.
Infrastructure sits behind `typing.Protocol` adapters — `MessagingProvider`, `ObjectStorage`
(and, in later phases, `AiProvider`, `PaymentGateway`) — so the domain never imports a vendor
SDK. WhatsApp is an external interface: the engine consumes only the normalized
`IncomingMessage`/`OutgoingMessage` models, never Meta payloads.

**Tenant isolation:** `business` is the tenant root. Every business-owned query is filtered by
the `business_id` taken from the authenticated principal — never from client-supplied data.

### Modules (`app/`)
| Package | Responsibility | Phase |
|---|---|---|
| `common/` | Money, exceptions, domain events, security (JWT/RBAC/PIN), `ObjectStorage`, `MessagingProvider` | 1 |
| `config.py` · `db.py` · `redis_client.py` · `providers.py` | Settings, engine/session, Redis, composition root | 1 |
| `auth/` | Registration/login, JWT access+refresh (+ rotation/revocation), RBAC, PIN step-up | 2 |
| `business/` | Business profile/settings, WhatsApp link, payment preference, Business PIN | 2 |
| `catalog/` | Categories, products, product images, filtering, soft delete | 3 |

## Local development
```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows (Git Bash)
pip install -e ".[dev,storage]"
cp .env.example .env

# Start datastores, then apply migrations, then run the app:
docker compose up -d db redis minio
alembic upgrade head
uvicorn app.main:app --reload --port 8080
```
Schema changes go through Alembic — never `create_all` in the runtime path.

## Configuration
All settings come from the environment / `.env` (see `.env.example`); no secrets in code.
Key vars: `DB_URL`, `REDIS_URL`, `JWT_SECRET`, `STORAGE_BACKEND` (`memory`|`s3`), the `S3_*` /
`WA_*` / `RZP_*` / `AI_*` groups, `DEFAULT_TAX_RATE` (configurable, no hard-coded GST) and
`AI_CONFIDENCE_THRESHOLD` (dev default `0.6`).

## Database migrations
```bash
alembic upgrade head          # apply all migrations to an empty DB
alembic downgrade -1          # roll back one revision
alembic revision --autogenerate -m "message"
```
History: `2fe2d845a574` (business + users) → `4a67448a6c59` (catalog: category, product,
product_image).

## API surface (Phases 1–3)
```
GET  /healthz

POST /api/auth/register            # onboarding: business + OWNER (atomic)
POST /api/auth/login               # JWT access + refresh
POST /api/auth/refresh             # rotates + revokes the old refresh token
POST /api/auth/logout              # revokes the refresh token
POST /api/auth/users               # OWNER: add a user
GET  /api/auth/users               # OWNER: list own-business users
GET  /api/auth/users/{id}          # tenant-scoped (404 cross-tenant)

GET   /api/business/me
PATCH /api/business/me                       # OWNER
PUT   /api/business/me/whatsapp              # OWNER (number unique across businesses)
POST  /api/business/me/pin                   # OWNER: set Business PIN
PUT   /api/business/me/payment-preferences   # OWNER + Business PIN (sensitive)

POST /api/categories                         # OWNER/EMPLOYEE
GET  /api/categories
POST /api/products                           # OWNER/EMPLOYEE
GET  /api/products?q=&category_id=           # keyword + category filter, excludes deleted
GET  /api/products/{id}
PATCH /api/products/{id}                      # OWNER/EMPLOYEE
DELETE /api/products/{id}                     # OWNER/EMPLOYEE + Business PIN (soft delete)
POST /api/products/{id}/images                # OWNER/EMPLOYEE (multipart, image/* only)
GET  /api/products/{id}/images
```

### Auth quickstart
```bash
# 1) register → returns access + refresh tokens
curl -X POST http://localhost:8080/api/auth/register -H "Content-Type: application/json" \
  -d '{"business_name":"Kirana","category":"grocery","contact_number":"+919812345678",
       "address":"5 Bazaar St","email":"owner@shop.co","password":"demopass123"}'

# 2) use the access token
curl http://localhost:8080/api/business/me -H "Authorization: Bearer <ACCESS_TOKEN>"
```
Sensitive actions (delete product, change payout settings) also require the Business PIN via the
`X-Business-PIN` header.

## Quality gates
```bash
ruff check . && ruff format --check .
mypy app                      # strict
bandit -r app
pytest --cov=app --cov-report=term-missing
```
Integration tests run against PostgreSQL (a `vyapar_test` database on the compose `db` service),
each test wrapped in a rolled-back transaction. Bring `db` up first: `docker compose up -d db`.

## Docker (full stack)
```bash
cp .env.example .env
docker compose up -d --build
docker compose exec app alembic upgrade head
curl http://localhost:8080/healthz            # {"status":"ok",...}
```
Services: `app` (FastAPI), `db` (Postgres 16), `redis` (7), `minio` (S3-compatible). The
`S3Storage` adapter auto-provisions its bucket on first use.

## Object storage
Product images and (later) invoice PDFs live in object storage, referenced by URL — never stored
in Postgres. `STORAGE_BACKEND=memory` uses an in-process fake (dev/tests); `s3` targets MinIO/S3.

## Dev message simulation
Pushes a message through the `MessagingProvider` boundary without WhatsApp. The full conversation
pipeline (AI Gateway → Intent Router → Handler → Reply Builder) arrives in a later phase; until
then this endpoint acknowledges via the provider to prove the boundary end to end. Mounted outside
production only.
```bash
curl -X POST http://localhost:8080/dev/simulate-message -H "Content-Type: application/json" \
  -d '{"business_id":1,"sender_phone":"+9199","text":"add 10 notebooks"}'
```
