# Local AI with Ollama

The AI layer runs fully locally through [Ollama](https://ollama.com). Ollama is a
concrete implementation of the existing AI-provider abstraction — the domain
services never import it. Selecting it is a configuration choice, not a code
change.

## Recommended local setup

**Run Ollama on the host** (simplest, uses your GPU directly):

1. Install Ollama and start the server (the desktop app starts it automatically;
   otherwise `ollama serve`).
2. Pull the models you intend to use:
   ```
   ollama pull qwen2.5:7b          # conversation / intent (default)
   ollama pull qwen2.5vl:3b        # catalog vision
   ollama pull mxbai-embed-large   # embeddings (optional, unwired)
   # lighter, faster conversation alternatives:
   ollama pull qwen2.5:3b-instruct
   ollama pull llama3.2:3b
   ```
3. Configure the app (`.env`):
   ```
   AI_PROVIDER=ollama
   OLLAMA_BASE_URL=http://localhost:11434
   OLLAMA_CONVERSATION_MODEL=qwen2.5:7b
   OLLAMA_CATALOG_MODEL=qwen2.5vl:3b
   ```

**Or run Ollama as an optional Docker service** (no GPU passthrough configured):

```
docker compose --profile ollama up -d ollama
docker compose exec ollama ollama pull qwen2.5:7b
```
Then set `OLLAMA_BASE_URL=http://ollama:11434` (containers) or, if the app runs in
a container but Ollama runs on the host, `http://host.docker.internal:11434`.

The Ollama service is behind a compose **profile** so it never starts by default
and is never baked into the application image.

## How it plugs in

```
ConversationService ─▶ ConversationAiProvider ─▶ OllamaConversationAdapter ─▶ Ollama
CatalogAiService    ─▶ AiProvider             ─▶ OllamaAdapter (vision)     ─▶ Ollama
```

- Wire format lives only in the adapters (`app/conversation/adapters/ollama.py`,
  `app/catalogai/adapters/ollama.py`). They call `/api/generate` with Ollama's
  structured `format` (a JSON schema) and `temperature=0`.
- The response is **re-validated** through `ResolvedIntent` / `AiDraftPayload`;
  malformed or hallucinated output becomes a typed error, never an unsafe action.
- No model name is hard-coded — everything comes from `Settings`.

## Verifying connectivity and models

```
curl http://localhost:11434/api/version         # server up?
ollama list                                      # models pulled?
python -m evals.run_eval --provider ollama       # end-to-end accuracy + latency
```

If the server is down or a model is missing, the adapter raises
`ConversationAiUnavailable` / `ConversationAiConfigError`; the conversation
service replies with a controlled, localized "please try again" message and
**never fabricates** a business value.
</content>
