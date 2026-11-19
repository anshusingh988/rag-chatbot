# Full-Stack RAG Chatbot

Upload documents -> ask questions -> get streamed, **cited** answers grounded in those documents.
(Implements the synopsis: ingestion, hybrid retrieval, LLM orchestration, streaming chat UI, admin panel.)

## Quick start (local, ~2 minutes)

```bash
# 1. Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # optional; without any key it runs in offline demo mode
uvicorn app.main:app --reload --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev                               # http://localhost:5173
```

1. Open the app and **Register** - the first account becomes **admin**.
2. Go to **Knowledge base** -> upload `sample_docs/company_policy.md` (or your own PDF/DOCX/HTML/MD/TXT).
3. Go to **Chat** and ask: *"How many days of paid leave do I get?"*, *"What does ERR-4021 mean?"*

Single-container deploy: `cp .env.example .env` (add keys) then `docker compose up --build` -> http://localhost:8000

## Run the tests
```bash
cd backend && source .venv/bin/activate && pytest -q     # 9 tests: chunking, auth/RBAC, e2e chat, citations, refusal, injection
```

## Architecture (what maps to the synopsis)

| Synopsis | This implementation | File |
|---|---|---|
| Ingestion + chunking (PDF/DOCX/HTML/MD/TXT) | format parsers, heading/page metadata, sentence-aware chunks with overlap | `backend/app/ingest.py` |
| Embeddings | pluggable: `hash` (offline default), `st` (sentence-transformers), `openai` | `embeddings.py` |
| Hybrid retrieval | dense cosine + BM25 -> Reciprocal Rank Fusion -> re-rank | `retrieval.py` |
| Grounded prompt + streaming + citations | `[n]` markers mapped back to source chunks; WebSocket token streaming | `chat.py`, `main.py` |
| "Say when not enough evidence" | evidence threshold -> fixed refusal, no LLM call | `chat.py` |
| Conversation memory | last N turns + running summary of older turns | `chat.py` |
| Provider abstraction + failover | Anthropic Claude / OpenAI / mock | `llm.py` |
| Auth + RBAC | JWT access + rotating refresh tokens, admin/user roles | `auth.py` |
| Prompt-injection safeguard | regex screening + "context is data" system rule | `chat.py` |
| React + TS + Tailwind UI | login, streaming chat, citation badges, history, admin dashboard | `frontend/src` |
| Docker | one image serves API + built frontend | `Dockerfile` |

## Honest deviations from the synopsis (MVP vs. production)
These are deliberate for a one-day, runs-anywhere build. Each is a swap behind an existing interface:

- **SQLite + in-memory numpy index** instead of PostgreSQL + Pinecone/pgvector/Milvus (schema is portable).
- **Hash embedder by default** (works offline, strong on exact terms, weaker on paraphrases). For real semantic
  search: `pip install sentence-transformers` and `EMBEDDER=st` (chunks are re-embedded automatically on startup).
- **Lightweight lexical+dense re-ranker** instead of a cross-encoder (`HybridIndex.rerank`).
- **Single FastAPI service** instead of microservices + Node auth + NGINX + Kubernetes; Redis, Terraform,
  Datadog, MLflow, RAGAS are not included. React state hooks instead of Redux Toolkit / React Query.
- Scanned PDFs (OCR) unsupported. Small talk like "hi" gets the "not enough information" reply.

## Good next steps for the report / viva
1. Build a 30-50 question eval set and measure recall@5 and groundedness (RAGAS) - your synopsis targets 90% / 4.3.
2. Switch to `EMBEDDER=st` and compare recall@5 against the hash baseline (a nice results table).
3. Add a cross-encoder re-ranker and plot the improvement.
