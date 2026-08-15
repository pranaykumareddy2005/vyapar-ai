# Multilingual Conversational Support

The conversational assistant understands business requests in **English, Telugu,
and Hindi** — in native script, romanized (Latin) form, and code-mixed — and
replies in the user's language. Language is metadata: it never changes the
business operation or the numbers.

## Flow

```
User message (any language)
      │
      ▼
AI provider → structured intent (language-neutral)   ← understanding
      │
      ▼
Validation + confidence gate + tenant from JWT
      │
      ▼
Domain service (InventoryService / CatalogService)   ← authoritative values
      │
      ▼
Deterministic reply template in the user's language  ← phrasing only
```

The same request maps to the same intent regardless of language:

| Message | Intent | Entities |
|---------|--------|----------|
| `add 20 notebooks` | ADJUST_STOCK | qty 20, INCREASE |
| `20 నోట్‌బుక్స్ స్టాక్‌లో చేర్చండి` | ADJUST_STOCK | qty 20, INCREASE |
| `20 नोटबुक स्टॉक में जोड़ो` | ADJUST_STOCK | qty 20, INCREASE |

## Language detection (who decides the reply language)

Reply language is decided **deterministically from the user's own text**, not by
the model (`app/conversation/language.py`), so it cannot be spoofed:

- Telugu script (U+0C00..U+0C7F) → reply in Telugu.
- Devanagari (U+0900..U+097F) → reply in Hindi.
- Latin / undetermined (e.g. romanized `notebook kitne hain`) → use the model's
  language hint if it gave one, else English.

Measured model language detection on the eval set: **96.8%** (30/31); the
authoritative *reply* language is script-derived, so a model miss on Latin/mixed
input cannot select the wrong operation.

## Response generation (business facts are never invented)

Replies are built from **per-language templates** (`app/conversation/responses.py`)
into which the domain service's real values are interpolated. The AI chooses the
template and language; it never supplies the number:

| Language | Reply |
|----------|-------|
| English | `Notebook currently has 27 units in stock.` |
| Telugu | `Notebookలో ప్రస్తుతం 27 యూనిట్లు స్టాక్‌లో ఉన్నాయి.` |
| Hindi | `Notebook में अभी 27 इकाइयाँ स्टॉक में हैं।` |

For critical operations the templates are fully deterministic — the model is not
asked to phrase stock levels, prices, or order/payment status.

English output is byte-identical to the original single-language wording, so
existing behaviour is unchanged.

## Security across languages

Switching language grants **no** extra permission:

- `ResolvedIntent` carries no `business_id`/`product_id` (extra keys dropped);
  tenant always comes from the JWT principal.
- The confidence gate blocks low-confidence actionable intents in every language.
- Multilingual prompt-injection ("ignore instructions", "delete all stock",
  "switch business") is instructed to classify as UNSUPPORTED; measured injection
  rejection at the model layer is **100%** on the eval set, and even a
  misclassification is contained because the mutation path still requires a
  resolved product, a positive quantity, and a passing confidence check.

## Semantic search (future)

`OllamaEmbeddingClient` and `EmbeddingProvider` exist as scaffolding for
multilingual semantic product search but are **not wired** to the live resolver:
the current keyword resolver via `CatalogService` is sufficient, and adding a
vector store now would be infrastructure for appearance only. When wired, embed
product text per `business_id`, keep search tenant-scoped, and never expose
internal ids to the model. For production multilingual embeddings, prefer `bge-m3`.

## Adding a language

1. Add the value to `Language` in `app/conversation/schemas.py`.
2. Add its templates to each builder in `app/conversation/responses.py`.
3. If it has a distinct script, extend `detect_script_language`.
4. Add cases to `evals/dataset.py` and re-run the eval.

No domain/service/database change is required — the data model stays
language-neutral.
</content>
