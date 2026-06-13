# Deployment & Re-ingestion Runbook (DigitalOcean Droplet)

Target: single DO droplet running the app + Postgres/pgvector via docker-compose.
LLM: deepseek-v4-flash via Volcengine ark (set in `.env`).

> **Droplet sizing:** local `bge-m3` embeddings + `bge-reranker-v2-m3` need
> ~2.5–3 GB RAM and are CPU-slow. Use a droplet with **≥ 4 GB RAM**. If the
> droplet is smaller, either (a) embed/index on a bigger machine and copy the
> `pgdata` volume, or (b) switch to a hosted embedding API
> (`EMBEDDING_PROVIDER=openai`) — see "Embedding runtime" below.

---

## 1. Get the latest code + config

```bash
cd /opt/rag           # or wherever the repo lives on the droplet
git pull
cp .env.example .env  # first time only
# Edit .env: set LLM_API_KEY (deepseek/Volcengine) and keep DB_* defaults.
```

## 2. Start Postgres + pgvector

```bash
docker compose up -d db
docker compose exec db pg_isready -U rag -d rag    # expect "accepting connections"
```

## 3. Install dependencies (host or app container)

Host venv:
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Scrapling's browser backend (only needed for anti-bot 403 sites: Yukon,
# Nunavut, Manitoba). Skips fine if you don't install it.
scrapling install || true
```

First run downloads the bge-m3 + reranker models (~2 GB) into the HF cache.

## 4. Re-ingest the full corpus (crawl → extract → chunk → embed → index)

```bash
# Ingest all registry sources (all 13 provinces/territories + federal).
python -m src.ingestion_module all

# Inject Express Entry draw data (live, or --offline for the local snapshot).
python -m src.fetch_draws_data            # live from IRCC
# python -m src.fetch_draws_data --offline
```

This rewrites `data/processed/chunks.jsonl` AND upserts into pgvector. Re-running
is safe: ingest is idempotent per `doc_id` (refresh semantics) and dedups by
content hash.

## 5. Verify

```bash
# Vector store populated?
python -c "from src import vector_store as v; print('rows:', v.count())"

# Retrieval quality baseline on the new index:
python -m eval.retrieval_metrics --k 1 3 5 10

# App readiness probe (expects {"ready": true}):
curl -s localhost:5050/api/ready | python -m json.tool
```

## 6. (Re)start the app

```bash
docker compose up -d --build app
# or, host: gunicorn -w 2 -k gthread --threads 4 -b 0.0.0.0:5050 src.app:app
```

---

## Embedding runtime (deferred decision)

`EMBEDDING_PROVIDER` controls this:
- `bge` (default): local multilingual bge-m3. Best EN/ZH quality, free, needs RAM.
- `openai`: hosted embeddings via the OpenAI-compatible endpoint. Use on small
  droplets to avoid loading torch; set `EMBEDDING_MODEL` accordingly.
- `fake`: deterministic, for CI/tests only — do NOT use in production.

If you change the embedding provider/model, the vector dimension changes, so
**re-run step 4** to rebuild the index (`vector_store` recreates the table at the
new dimension).

## Keeping data fresh

IRCC publishes Express Entry draws ~biweekly; provincial pages change less
predictably. Re-run step 4 on a schedule (e.g. weekly cron). `effective_date` is
now captured per chunk, so stale content is detectable.

## Anti-bot sources

Plain HTTP fetch returns 403 for Yukon, Nunavut, and Manitoba's portals. The
crawler escalates to Scrapling's browser-based `StealthyFetcher` automatically
when `scrapling install` has provisioned the browser; otherwise those few pages
are skipped (logged), and the rest of the corpus ingests normally.
