# Ollama Model Selection Report

This report documents the local-inference models wired into the AI layer, why each
was chosen, and how they were measured. All figures below were produced on the
development machine described; re-run `python -m evals.run_eval --provider ollama`
to reproduce the accuracy numbers on your own hardware.

## 1. Hardware detected

| Resource | Value |
|----------|-------|
| CPU | 16 logical cores |
| RAM | 15.3 GB |
| GPU | NVIDIA GeForce RTX 3050 Laptop, **6 GB VRAM** |
| OS | Windows 11 |

The 6 GB VRAM ceiling is the binding constraint: a Q4-quantized 7B model (~4.7 GB
of weights) fits with room for context; larger models spill to CPU/RAM and slow
sharply. Model choices below respect that ceiling.

## 2. Ollama

| Item | Value |
|------|-------|
| Ollama version | 0.17.7 |
| API | HTTP, `http://localhost:11434` (`/api/generate`, `/api/embeddings`) |
| Integration | `OllamaConversationAdapter`, `OllamaAdapter` (vision), `OllamaEmbeddingClient` — all behind the existing provider Protocols |

## 3. Models selected (configurable — never hard-coded)

| Setting | Default | Size | Role |
|---------|---------|------|------|
| `OLLAMA_CONVERSATION_MODEL` | `qwen2.5:7b` | 4.7 GB | Intent classification + multilingual understanding + strict JSON |
| `OLLAMA_CATALOG_MODEL` | `qwen2.5vl:3b` | 3.2 GB | Vision → structured catalog draft from a product image |
| `OLLAMA_EMBEDDING_MODEL` | `mxbai-embed-large` | 669 MB | Reserved for future semantic product search (not yet wired) |
| Lightweight alt. (conversation) | `qwen2.5:3b-instruct` / `llama3.2:3b` | 1.9 / 2.0 GB | Lower-latency intent classification where some accuracy can be traded |

### Why each model

- **`qwen2.5:7b` (conversation).** Qwen2.5-Instruct is strong at instruction
  following and **strict JSON**, and notably capable across **Hindi and Telugu**
  (native script, romanized, and code-mixed). Its Q4 weights (~4.7 GB) fit the
  6 GB GPU. This is the accuracy-priority default; the conversation path is where
  multilingual understanding matters most.
- **`qwen2.5vl:3b` (catalog vision).** A compact vision-language model that fits
  comfortably alongside headroom for the image, adequate for drafting a product
  name/description/category/tags. The merchant still reviews and supplies price —
  the model never sets price.
- **`mxbai-embed-large` (embeddings).** A small, already-available embedding model.
  Embeddings are **scaffolding only** right now (see `multilingual.md` §Semantic
  search); for production multilingual retrieval prefer `bge-m3`.
- **Lightweight alternatives.** `qwen2.5:3b-instruct` and `llama3.2:3b` are pulled
  and available for latency-sensitive deployments; switch by changing the env var.

### Expected resource usage

| Model | Weights | Fits 6 GB GPU? | Notes |
|-------|---------|----------------|-------|
| `qwen2.5:7b` | ~4.7 GB | Yes (Q4) | Primary conversation model |
| `qwen2.5:3b-instruct` | ~1.9 GB | Yes, easily | Lower-latency alternative |
| `qwen2.5vl:3b` | ~3.2 GB | Yes | Vision/catalog |
| `mxbai-embed-large` | ~0.67 GB | Yes | Embeddings |

## 4. Measured accuracy (conversation, `qwen2.5:7b`)

From `python -m evals.run_eval --provider ollama` over the 31-case multilingual
dataset (`evals/dataset.py`); full breakdown in `evaluation_report.md`:

| Metric | Result |
|--------|--------|
| Intent accuracy | **93.5%** (29/31) |
| Quantity extraction | **100%** (11/11) |
| Direction extraction | **100%** (12/12) |
| Product resolution | **95.2%** (20/21) |
| Model language detection | **96.8%** (30/31) |
| Unsupported detection | **100%** (8/8) |
| Injection rejection (model layer) | **100%** (5/5) |
| Provider errors | **0 / 31** |

Per-language intent accuracy: English **88.2%** (15/17 — the two misses are both
English ambiguity edge cases: `"do something with notebooks"`, `"hi"`), Telugu
**100%** (5/5), Hindi **100%** (6/6), code-mixed **100%** (3/3).

## 5. Performance

| Item | Value |
|------|-------|
| Avg latency / request | ~6.0–6.9 s across runs (RTX 3050 6 GB, includes JSON-constrained decode) |
| Structured-output success | 31/31 (0 malformed) |
| Failure rate | 0% |

Latency is dominated by local decode on a modest laptop GPU; a 3B model roughly
halves it. Latency was measured wall-clock per `resolve()` call in the harness.

## 6. Role assignment summary

- **Conversation / intent:** `qwen2.5:7b` (default) — accuracy-priority.
- **Catalog generation:** `qwen2.5vl:3b`.
- **Embeddings:** `mxbai-embed-large` (unwired; `bge-m3` recommended for prod).

## 7. Fallback behavior

- The provider is chosen **explicitly** via `AI_PROVIDER`; there is **no silent
  fallback** to the mock in production (that configuration fails loudly).
- If Ollama is unreachable or the model is not pulled, the adapter raises a typed
  error (`ConversationAiUnavailable` / `...ConfigError`), which the service turns
  into a controlled, localized "try again" reply — it never fabricates a result.
- `AI_PROVIDER=mock` is permitted only outside production, for deterministic
  dev/test runs.

## 8. Honesty notes

- Accuracy/latency above are from **real local inference** on the machine in §1,
  not estimates. Re-run the eval to reproduce.
- The Gemini adapters remain HTTP-mock-tested only (no key exercised here).
- The catalog **vision** path and the embedding client are implemented and
  unit-tested against mocked HTTP; broad live vision accuracy was not benchmarked.
</content>
