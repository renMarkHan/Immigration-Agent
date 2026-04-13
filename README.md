# Canada Immigration & PR Navigator

Team 3 — MVP implementation.

## What this project includes

- Shared schema contracts for all modules (Pydantic)
- Multi-turn intake state machine with profile collection
- End-to-end orchestrator with intent routing, L3 safety gate, and D-003 retry logic
- Scoring-based intent classifier (5 intents, typo-tolerant, personal-context amplifier)
- Risk-level routing with decision trace (`risk_explain` in every response)
- Hybrid BM25 + vector retrieval (ChromaDB, local index)
- CRS calculator policy tool
- Action-specific LLM prompt templates (4 action types, QA sub-type selection)
- Flask web UI served on port 5050
- Express Entry draw data ingestion from IRCC JSON API
- Eval harness with intent accuracy, confusion matrix, and citation checks

## Project structure

```text
.
├── .env
├── requirements.txt
├── src/
│   ├── schemas.py              — Pydantic contracts (IntakeProfile, FinalAnswer, …)
│   ├── llm_client.py           — LLM endpoint wrapper
│   ├── orchestrator.py         — Pipeline wiring (intent → retrieval → tools → answer)
│   ├── agent_module.py         — Intent classifier, risk routing, answer builder
│   ├── retrieval_module.py     — Hybrid BM25 + vector retrieval (ChromaDB)
│   ├── ingestion_module.py     — HTML scraping, chunking, indexing
│   ├── fetch_draws_data.py     — Express Entry draw data fetcher (IRCC JSON API)
│   ├── policy_tool_module.py   — CRS calculator, pathway backbone tools
│   ├── intake.py               — Multi-turn intake state machine
│   ├── app.py                  — Flask web server (port 5050)
│   ├── chat_cli.py             — Terminal interactive chat loop
│   ├── main.py                 — Smoke test (connectivity + mock pipeline)
│   └── agent/
│       └── system_prompt.py    — System prompt v1, risk-tier templates
├── data/
│   ├── raw/                    — Scraped HTML + ee-rounds-data.json snapshot
│   └── processed/
│       └── chunks.jsonl        — Chunked policy text (BM25 + embedding input)
├── chroma_db/                  — Persistent ChromaDB vector index
└── eval/
    ├── samples.jsonl           — 15 eval samples (intent labels, risk levels)
    └── run_eval.py             — Eval harness with intent confusion matrix
```

## Prerequisites

- Python 3.11
- pip + venv
- Valid student bearer token for LLM endpoint
- ChromaDB index built (see **Build retrieval index** below)

## Environment setup

1. Create and activate venv:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure `.env`:

```dotenv
LLM_ENDPOINT=https://rsm-8430-finalproject.bjlkeng.io/v1/chat/completions
LLM_API_KEY=<your_student_id_token>
LLM_MODEL=qwen3-30b-a3b-fp8
```

## Build retrieval index

Run once before first use (or after adding new data):

```bash
python -m src.ingestion_module
python -m src.fetch_draws_data --offline   # inject Express Entry draw data
```

`--offline` uses the local snapshot in `data/raw/ee-rounds-data.json`.
Omit `--offline` to fetch the latest draw results live from IRCC.

## Launch web chatbox (recommended)

```bash
python -m src.app
```

Opens at **http://localhost:5050**. Supports free-text queries — no profile
fields required for factual and policy questions.

## Run interactive chat CLI

Terminal-only, no web UI:

```bash
python -m src.chat_cli
```

Available commands: `/help`, `/show`, `/set province <value>`,
`/set program <value>`, `/set stream <value>`, `/clear`, `/exit`

## Run smoke test

```bash
python -m src.main
```

Tests LLM endpoint connectivity and runs a mock pipeline pass.

## Run eval harness

```bash
python -m eval.run_eval
```

Output: `eval/results/latest.json`

Metrics reported:
- `pass_rate` — answer content + citation checks
- `intent_accuracy` — classifier accuracy over labelled samples
- `intent_confusion_matrix` — per-intent breakdown

Intent-only fast check (no LLM call, <5 s):

```bash
python -m eval.run_eval --intent-only
```

## Keep draw data current

IRCC publishes new draw results roughly every two weeks. Refresh:

```bash
python -m src.fetch_draws_data          # live fetch + rebuild index
python -m src.fetch_draws_data --offline # rebuild from local snapshot only
```

## Run Ontario retrieval demo

```bash
python -m src.demo_ontario_flow
```

Demonstrates ingest → retrieve → cite for the OINP Masters Graduate Stream.

## Role ownership map

- Role A (Ella): `src/agent_module.py` — intent classifier, risk routing, answer builder
- Role B (Keqing): `src/retrieval_module.py`, `src/agent/system_prompt.py` — hybrid retrieval, system prompt
- Role C (Yuhan): `src/policy_tool_module.py`, `src/llm_client.py`, `src/schemas.py`, `src/orchestrator.py` — tools, contracts, pipeline
- Role D (Chao): `src/ingestion_module.py`, `src/fetch_draws_data.py` — data ingestion, draw data
- Role E (Ehraaz): `src/app.py`, `src/intake.py` — web server, intake state machine

## Integration rules

- Do not change function signatures without notifying Role E + Framework Owner.
- Add all cross-module data fields in `src/schemas.py` only.
- Keep citation fields intact in every `FinalAnswer`:
  - `source_url`
  - `section_or_title`
  - `effective_date_or_last_updated_or_unknown`
  - `accessed_at`
- After meaningful changes, run `python -m eval.run_eval`.
- The intake gate in `src/app.py` is bypassed for `qa`, `general`, and `calculate`
  intents — these query types do not require a full user profile.

## Known limitations

- `qwen3-30b-a3b-fp8` in reasoning mode consumes token budget for thinking before
  generating output. Use `max_tokens ≥ 2048` (already set in `_call_llm`).
- IRCC draw cutoff numbers are loaded via JavaScript on the rounds page — static
  HTML scraping captures no actual values. Use `python -m src.fetch_draws_data`
  to fetch the data from the IRCC JSON API instead.
- ChromaDB default collection cap is 2000 documents; the full corpus is 2451 chunks.
  Run `python -m src.ingestion_module` followed by `python -m src.fetch_draws_data`
  to rebuild with the full set.

## Current implementation status

- ✅ Shared contracts (schemas) — `FinalAnswer` includes `risk_explain`, `intent_scores`, `intent_top2`, `intent_ambiguous`
- ✅ Orchestrator pipeline — intent → L3 safety gate → retrieval → tools → risk routing → answer → retry
- ✅ Intent classifier — scoring-based, 5 intents, typo-tolerant, personal-context amplifier
- ✅ Risk routing with explain trace — L1/L2/L3 with decision steps in every response
- ✅ Hybrid retrieval — BM25 (weight 0.6) + ChromaDB vector (weight 0.4), local index
- ✅ CRS calculator policy tool
- ✅ Action-specific prompt templates — 4 action types; QA sub-typed (factual vs document)
- ✅ Web UI — Flask + `python -m src.app` → http://localhost:5050
- ✅ Multi-turn intake — bypassed for factual/policy queries that don't need profile fields
- ✅ Express Entry draw data — `src/fetch_draws_data.py` injects cutoff history into index
- ✅ Eval harness — pass rate, intent accuracy, confusion matrix; 11/11 intent samples pass

## Related docs

See docs index for team workflow and frozen decisions:
- `docs/README.md`
- `docs/Decision-Log.md`
- `.github/copilot-instructions.md`
