# AI Assistant Handoff (Scaffold Context)

Purpose: Let any teammate AI assistant understand the scaffold and role tasks immediately, without re-discovering project decisions.

Last Updated: 2026-04-07

---

## 1) Project Snapshot

- Project: Canada Immigration & PR Navigator
- Team: Chao Tang, Yuhan Ren, Ehraaz Atif, Ella Lu, Keqing Wang
- Paradigm: Evals-Driven Development (EDD)
- Current Stage: Planning -> Scaffold implementation starts now
- MVP Deadline: 2026-04-14

---

## 2) Frozen Decisions (Do Not Re-open During MVP Build)

1. Refusal Policy: Option A (tiered answer/clarify/refuse)
2. Minimum Required Fields: use agreed field set + missing-field rules
3. No-Evidence Flow: Hybrid by risk tier (L1 clarify, L2 clarify once then refuse, L3 direct refuse)
4. Retrieval: hybrid BM25 + vector + reranker + metadata filters
5. Eval priorities: factual + citation first; hallucination/refusal are mandatory safety gates
6. Tool scope: CRS calculator MVP covers Federal Express Entry only
7. Demo scope: all 4 Actions must run end-to-end

Source of truth: docs/Decision-Log.md

---

## 3) Execution Mode

- Framework-first mode is active.
- Yuhan Ren builds the minimal scaffold first.
- Others build in parallel against frozen contracts.
- Integration is daily (not end-loaded).

## 3.1) Current Runtime Constraints (This phase)

- Model: `qwen3-30b-a3b-fp8` (reasoning enabled)
- Hosted endpoint: `https://rsm-8430-finalproject.bjlkeng.io`
- Constraint type: current project-phase constraint (not a permanent future constraint)

---

## 4) Role Mapping

- Role A Data/Retrieval: Ella Lu
- Role B Agent/Prompt: Keqing Wang
- Role C Policy/Tools + Framework Owner: Yuhan Ren
- Role D Eval/Quality: Chao Tang
- Role E Integration/UX: Ehraaz Atif

---

## 5) What the Minimal Scaffold Must Contain

1. A single runnable entry path (CLI or app entry) that can execute one full mocked flow.
2. Shared request/response schemas for:
   - intake profile
   - retrieval request/result
   - tool request/result
   - final answer with citations
3. Risk routing contract (L1/L2/L3) and no-evidence fallback policy hooks.
4. Logging schema placeholders:
   - session_id, normalized_intent, retrieval_sources, tool_calls, decision_type, risk_level, citations, timestamp.
5. Eval harness stub:
   - load eval samples
   - run pipeline
   - output score report template.
6. Module boundaries:
   - retrieval module
   - agent/router module
   - policy/tool module
   - eval module
   - integration orchestrator.

---

## 6) Role-Specific First Tasks

### Role A (Ella)
- Build retrieval module with baseline parameters.
- Implement metadata-aware retrieval response format.
- Provide retrieval smoke test examples.

### Role B (Keqing)
- Draft System Prompt v1 with refusal/citation constraints.
- Implement intake + routing skeleton hooks.
- Encode no-evidence behavior by risk tier.

### Role C (Yuhan)
- Validate source URLs and policy mapping.
- Implement Federal CRS calculator function + schema.
- Define citation section/title normalization rules.
- Build scaffold structure and publish shared contracts.

### Role D (Chao)
- Build 30-seed eval set template and scoring script skeleton.
- Define factual/citation/hallucination/refusal scoring fields.
- Produce first baseline score report format.

### Role E (Ehraaz)
- Build integration runner and connect modules end-to-end.
- Run daily integration and maintain blocker tracking.
- Update docs/Decision-Log.md after integration milestones.

---

## 7) Non-Negotiable Constraints for AI Assistants

1. Do not change frozen decisions without a new decision-log update entry.
2. Any behavior change must include a measurable eval impact.
3. Do not remove citation fields from output schema.
4. Prefer small, testable changes and daily integration.

---

## 8) Read-First File Order for AI

1. docs/README.md
2. docs/Decision-Log.md
3. docs/Team-Decision-Checklist.md
4. docs/Team-Workflow-and-Roles.md
5. docs/AI-Assistant-Handoff.md (this file)

---

## 9) Current Build Status Snapshot (2026-04-07)

Completed now:
- Shared schemas contract and orchestrator wiring are in place.
- Endpoint connectivity path is operational.
- Minimal conversational CLI is available via `python -m src.chat_cli`.
- Smoke runner remains available via `python -m src.main`.
- Demonstrative Ontario retrieval flow is available via `python -m src.demo_ontario_flow`.

Still pending before high-quality answers:
- Real ingestion pipeline (scrape -> clean -> chunk -> index).
- Real retrieval implementation (BM25 + vector + rerank + metadata filters).
- Agent prompt/routing implementation with citation-grounded response synthesis.
- Policy tool implementation (Federal EE CRS calculator for MVP scope).

How teammate AIs should interpret current phase:
- This repo is now in "interactive scaffold" phase, not "production answer quality" phase.
- Prioritize replacing stubs with real implementations while preserving schemas and orchestrator contracts.

Ontario example process to follow:
1. Ingest source URL: https://www.ontario.ca/page/oinp-masters-graduate-stream
2. Query: "what is the requirement for ontario master graduate stream?"
3. Retrieval should hit section/title "Requirements"
4. Response should include citation fields from schema contract
