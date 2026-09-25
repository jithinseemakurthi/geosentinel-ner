# RAG Assistant — GeoSentinel-NER

> Implements NVIDIA **rag-blueprint v2.6.0** (`Apache-2.0`) — `.agents/skills/rag-blueprint/`

Retrieval-Augmented Generation over NER landslide knowledge: alerts, citizen reports, capitals, GSI/NDMA guidelines, IMD nowcast.

## Deployment modes (blueprint)

| Mode | Config | When |
|------|--------|------|
| Self-hosted (Docker) | `deploy/compose/.env` + `docker-compose-rag-server.yaml` + `nims.yaml` (LLM, embedding, reranker NIMs) | Local NIMs (`nim-llm`, `nemotron-embedding`, `nemotron-ranking`) |
| NVIDIA-hosted | `deploy/compose/nvdev.env` | No local NIMs, uses NVIDIA API |
| Library | `notebooks/config.yaml` / in-browser | No Docker — TF-IDF mock (this demo) |

The frontend auto-detects in order: dedicated `rag-server` `GET /api/v1/rag/v1/health` → **api-gateway LLM shims** `POST /api/v1/rag/v1/generate` & `POST /api/v1/assistant/query` (Groq/OpenAI/Together/Ollama/NVIDIA) → library TF-IDF + templated synthesis (no key).

## LLM integration (assistant section — no hardcoded data)

The assistant at `?tab=assistant` is now LLM-powered with **live** data, not hardcoded mocks:

* **Provider-agnostic OpenAI-compatible** — `services/api-gateway/app/main.py:475` `_resolve_llm_config()` reads `GEO_LLM_API_KEY` **or** `GROQ_API_KEY` / `OPENAI_API_KEY` / `TOGETHER_API_KEY` / `NGC_API_KEY` (via `AliasChoices` in `packages/geosentinel-shared/geosentinel_shared/config.py:157`). Auto-switches base URL/model to Groq `https://api.groq.com/openai/v1/chat/completions` (`llama-3.1-8b-instant`) or OpenAI `https://api.openai.com/v1/chat/completions` (`gpt-4o-mini`) when only the key is set. Ollama works keyless at `http://localhost:11434/v1/chat/completions`.
* **Dynamic knowledge** — guidelines are **not** hardcoded in `src/lib/ragIndex.ts` any more. `docs/guidelines/*.md` (6 files, front-matter `id`/`collection`/`title`) are loaded at runtime by `GET /api/v1/knowledge/guidelines` (`main.py:601`) and fetched by the browser via `loadGuidelinesFromBackend()`; `GROQ` etc. Alerts/reports/capitals come live from PostGIS (`_live_platform_context()` `main.py:461` + `GET /api/v1/knowledge/collections`). The RAG index rebuilds from `activeGuidelines + live alerts + live reports` — fallback to `FALLBACK_GUIDELINE_DOCS` only when the API is unreachable.
* **RAG + LLM shims** — `POST /api/v1/rag/v1/generate`, `POST /api/v1/rag/v1/search`, `GET /api/v1/rag/v1/health` are now served by the gateway itself (`main.py:658`) with server-side hybrid search + LLM synthesis, so the existing `src/services/rag.ts:42` `tryRemoteGenerate()` succeeds without deploying the external Blueprint rag-server. `src/services/rag.ts:44` `tryAssistantLLM()` additionally calls `POST /api/v1/assistant/query` with retrieved chunks as `rag_context` and conversation `history` (cited, token-counted).
* **Conversation memory** — `RagAssistant.tsx:60` `send()` now passes the last 8 turns as `history` to the LLM, displayed with provider badge (`remote:llama-3.1-8b-instant` vs `local synthesis`). `GET /api/v1/knowledge/guidelines` source is shown in the Knowledge base card.

### Quick start — use your own LLM key

```bash
# .env — pick one (no code change needed; restart api-gateway)
GROQ_API_KEY=gsk_...            # https://console.groq.com/keys  (free tier, fast)
# or
OPENAI_API_KEY=sk-...           # https://platform.openai.com/api-keys
# or Ollama local (no key)
GEO_LLM_BASE_URL=http://localhost:11434/v1/chat/completions
GEO_LLM_MODEL=llama3.1

docker compose up -d api-gateway   # rebuilds gateway; health at /api/v1/rag/v1/health will flip to api-gateway-llm
```

Verify: `curl http://localhost:8000/api/v1/rag/v1/health?check_dependencies=true` → `"deployment":"api-gateway-llm"` and `"llm":"llama-3.1-8b-instant"`.

## Features mapped from blueprint

| Blueprint reference | GeoSentinel usage |
|---------------------|-------------------|
| `references/configure/ingestion.md` (text-only) | Ingests demo alerts/reports + GSI/NDMA/IMD guideline docs; batch via `scripts/rag_ingest.py --collection geosentinel_guidelines` |
| `search-and-retrieval.md` (hybrid, topK, reranker) | Weighted hybrid `0.6 dense + 0.4 sparse` + cross-encoder boost; `APP_RETRIEVER_TOPK` slider; `RERANKER_SCORE_THRESHOLD 0.08` |
| `query-and-conversation.md` (rewriting) | NER-aware rewriting: expands district/rainfall terms (Aizawl→Mizoram ridge, f12/a3/a7) |
| `agentic-rag.md` | Planner → retrieval → rerank → synthesis → verification stages streamed as `event_type`/`stage`; toggle per-request `agentic:true` |
| `reasoning-and-generation.md` | Reasoning panel, citations, token usage, verification single-pass |
| `observability.md` | Retrieval inspector + health panel (future: Grafana/Prometheus via `observability.yaml`) |
| `data-catalog.md` | Collection selector (reports/alerts/capitals/guidelines/imd) + metadata filter `district==Aizawl` |
| `user-interface.md` | Chat UI, quick prompts, FAB |

## Frontend

- Types: `src/types/rag.ts` (mirrors `openapi_schema_rag_server.json` generate/search)
- Index: `src/lib/ragIndex.ts` (TF-IDF + hybrid + reranker; replace with `nemotron-embedding` NIM)
- Service: `src/services/rag.ts` (tries `/api/v1/rag/v1/generate`, falls back to local)
- UI: `src/components/RagAssistant.tsx` — health strip, collection toggles, topK/reranker/rewriting/agentic controls, chat with citations, reasoning, retrieval inspector
- Entry: `?tab=assistant` (`G A`), command palette, global FAB `✦`
- Docs: this file

## Ingestion script

```bash
python scripts/rag_ingest.py --collection geosentinel_guidelines --folder docs/guidelines --check-only
python scripts/rag_ingest.py --collection geosentinel_reports --folder data/reports
```

## Enable full self-hosted RAG (Linux GPU)

```bash
# 1. Clone blueprint
git clone https://github.com/NVIDIA-AI-Blueprints/rag && cd rag
# 2. Configure
cp deploy/compose/.env.example deploy/compose/.env
# set NGC_API_KEY, ENABLE_AGENTIC_RAG=true, APP_VECTORSTORE_SEARCHTYPE=hybrid, ENABLE_RERANKER=True
# 3. Start
docker compose -f deploy/compose/docker-compose-rag-server.yaml -f deploy/compose/vectordb.yaml -f deploy/compose/nims.yaml --profile rag up -d
# 4. Health
curl -s http://localhost:8081/v1/health?check_dependencies=true
# 5. Ingest
python scripts/batch_ingestion.py --folder ./docs --collection-name geosentinel_guidelines
```

The GeoSentinel frontend will then auto-switch from library to self-hosted (see `ragHealth()` detection).

## Troubleshooting

- **Services are not running** → deploy via `references/deploy.md` before configuring.
- **Reranker filtered too many** → lower `RERANKER_SCORE_THRESHOLD` 0.3→0.0 in `deploy/compose/.env`.
- **Hybrid needs re-ingestion** → recreate collections after switching `APP_VECTORSTORE_SEARCHTYPE`.
