# Canada Immigration & PR Navigator (MVP Scaffold)

Minimal framework-first scaffold for Team 3.

## What this scaffold includes

- Shared schema contracts for all modules (Pydantic)
- Module stubs for each role owner
- End-to-end orchestrator with D-003 retry behavior
- LLM connectivity wrapper for the course endpoint
- Eval harness stub (EDD) with sample set

## Project structure

```text
.
├── .env
├── requirements.txt
├── src/
│   ├── schemas.py
│   ├── llm_client.py
│   ├── retrieval_module.py
│   ├── policy_tool_module.py
│   ├── agent_module.py
│   ├── ingestion_module.py
│   ├── orchestrator.py
│   └── main.py
└── eval/
    ├── samples.jsonl
    └── run_eval.py
```

## Prerequisites

- Python 3.11
- pip + venv
- Valid student bearer token for LLM endpoint

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

## Run checks

Run scaffold smoke checks:

```bash
python -m src.main
```

This runs:
- Real endpoint connectivity test
- Mock pipeline run through orchestrator

## Run interactive chat CLI

Run the minimal conversational CLI:

```bash
python -m src.chat_cli
```

In CLI, you can ask questions directly and use these commands:
- /help
- /show
- /set province <value>
- /set program <value>
- /set stream <value>
- /clear
- /exit

Note: This is a terminal chat loop, not a web UI.

## Run Ontario retrieval process demo

Run this script to demonstrate the exact process shape requested by the team:

```bash
python -m src.demo_ontario_flow
```

What it demonstrates:
- Ingest source URL: https://www.ontario.ca/page/oinp-masters-graduate-stream
- Retrieve by query: "what is the requirement for ontario master graduate stream?"
- Return an answer with citation fields including source URL and section title.

Scope note:
- This is a demonstrative process implementation for teammate alignment.
- Final production retrieval/ingestion quality remains owned by module owners.

Run eval harness:

```bash
python -m eval.run_eval
```

Output file:
- `eval/results/latest.json`

## Role ownership map

- Role A (Ella): `src/agent_module.py`
- Role B (Keqing): `src/retrieval_module.py`
- Role C (Yuhan): `src/policy_tool_module.py`, `src/llm_client.py`, `src/schemas.py`
- Role D (Chao): `src/ingestion_module.py`
- Role E (Ehraaz): `src/orchestrator.py` integration

## Integration rules

- Do not change function signatures without notifying Role E + Framework Owner.
- Add all cross-module data fields in `src/schemas.py` only.
- Keep citation fields intact:
  - source_url
  - section_or_title
  - effective_date_or_last_updated_or_unknown
  - accessed_at
- After meaningful changes, run `python -m eval.run_eval`.

## Known current limitation

`qwen3-30b-a3b-fp8` may consume small `max_tokens` budgets in reasoning mode and return empty `content`.
For real generation tests, use a larger token budget (e.g., 512+).

- Retrieval and ingestion are still stubs until role owners complete module implementations.

## Current implementation status (for teammate handoff)

- Completed:
  - Shared contracts (schemas)
  - Orchestrator pipeline wiring
  - LLM endpoint client wrapper
  - Interactive CLI entry path (`python -m src.chat_cli`)
  - Eval harness skeleton
- Pending for fully useful answers:
  - Real ingestion pipeline (scrape/clean/chunk/index)
  - Real hybrid retrieval (BM25 + vector + rerank)
  - Agent prompt/routing and citation-grounded answer synthesis
  - Policy tools (CRS Federal EE for MVP)

## Related docs

See docs index for team workflow and frozen decisions:
- `docs/README.md`
- `docs/Decision-Log.md`
- `.github/copilot-instructions.md`
