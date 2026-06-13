# Canada Immigration & PR Navigator
## Decision Log v0.3

Date Initialized: 2026-04-07  
Team: Team 3 (Chao Tang, Yuhan Ren, Ehraaz Atif, Ella Lu, Keqing Wang)  
Purpose: Persistent record of planning and execution decisions for auditability and low-friction handoff.

---

## How to Use This Log

1. Add a new entry whenever a decision changes behavior, quality, safety, or timeline.
2. Keep one entry per decision. If updated, append an "Update" block under the same ID.
3. Every decision must include owner, rationale, impact, and verification method.
4. Execution updates must include at least one measurable signal (eval score, failure rate, latency, coverage).
5. Record decision intent and principle changes here; keep implementation details in commits/PRs.

---

## Decision Entries

### D-000 System Architecture: RAG vs GraphRAG vs Parametric Wiki (Frozen)
- Date: 2026-04-07 (recorded retroactively 2026-06-12)
- Owner: Team (Architecture)
- Status: Frozen
- Decision: Retrieval-Augmented Generation (RAG) over an external, citable
  document corpus. GraphRAG and a parametric "LLM wiki" were considered and
  rejected for this domain.
- Rationale:
  - Domain shape: ~90% of immigration questions are single-hop factual lookups
    ("what does this policy say"). Every answer must be traceable to an official
    URL. RAG's chunk → citation mapping satisfies the auditability requirement
    (see D-007) natively.
  - GraphRAG rejected: its advantage is multi-hop reasoning and cross-document
    entity aggregation. Our entity graph (program → stream → requirement) is
    real, but building and maintaining a knowledge graph over a small corpus is
    high-cost/low-return for our query mix, and graph maintenance compounds the
    freshness problem below.
  - Parametric / "LLM wiki" rejected: immigration policy changes frequently
    (Express Entry draws roughly every two weeks; dated policy updates).
    Relying on model memory makes refresh impossible and makes hallucination
    (unacceptable in a legal/policy context) far more likely. This is precisely
    why we built the L3 refusal gate (D-001) and hallucination audits (D-005).
- Impact: All ingestion, retrieval, citation, and eval design follows from this.
- Verification: Every factual answer carries >=1 official-source citation;
  freshness handled by re-ingestion (D-011), not model retraining.
- Re-evaluation trigger: If multi-hop comparison queries ("compare language
  requirements across N province streams") become a primary use case, revisit
  a hybrid GraphRAG layer over the existing corpus.

### D-001 Refusal Policy (Frozen)
- Date: 2026-04-07
- Owner: Team (final sign-off by Yuhan Ren)
- Status: Frozen
- Decision: Option A tiered policy (answer / clarify / refuse)
- Rationale: Legal-policy domain requires high safety and auditability.
- Impact: System prompt, routing, refusal templates, and compliance evals.
- Verification: Refusal compliance >= 98% on refusal subset.

### D-002 Minimum Required Intake Fields (Frozen)
- Date: 2026-04-07
- Owner: Team (Product + Policy)
- Status: Frozen
- Decision: Use recommended minimum fields and missing-field rules.
- Rules:
  - Missing > 2 required fields: no ranking, data collection only.
  - Missing 1-2 required fields: allow low-confidence pre-screening with warning.
- Impact: Intake flow, confidence labels, eligibility matching.
- Verification: 100% of test conversations enforce missing-field rules.

Update (Execution):
- Update Date: 2026-04-13
- Change Summary: In `src/app.py`, when sidebar `profile_overrides` are applied after `process_turn()`, the collecting prompt is now rebuilt from the updated profile. This prevents re-asking already-filled fields (for example age) and adds an explicit progress message that eligibility matching starts at 6/8 required fields.
- Why Changed: Users were confused when they had already filled profile fields in the sidebar but still saw repeated intake prompts generated from stale pre-override state.
- Expected Impact: Fewer repeated intake questions, clearer guidance on minimum profile completion, and reduced friction in Action 2 eligibility checks.
- Measured Result: `python test_completeness.py` remains green; collecting prompts now reflect post-override missing fields and include current progress (e.g., 4/8).
- Follow-up Actions: Add an end-to-end API test that posts `/api/chat` with partial/complete `profile_overrides` and asserts the collecting prompt never asks filled fields.
- Owner: Ehraaz Atif (Integration/UX)

### D-003 No-Evidence Handling Flow (Frozen)
- Date: 2026-04-07
- Owner: Team (Agent + Policy)
- Status: Frozen
- Decision: Option 3 Hybrid by risk tier.
- Rule Table:
  - L1: ask 1-2 clarification questions, retry retrieval once.
  - L2: ask clarification once; if still no evidence, refuse with compliant alternatives.
  - L3: direct refusal + RCIC suggestion.
- Retry Limit: max 1 retry.
- Estimated Build Time: 0.5-1.0 day.
- Impact: State machine, prompt policy, refusal behavior.
- Verification: 0 unresolved no-evidence loops in regression tests.

Update (Execution):
- Update Date: 2026-04-10
- Change Summary: Orchestrator now passes `user_text=profile.query` into `route_risk()` and `build_answer()` on both first pass and retry pass.
- Why Changed: Intent/risk routing in Role B depended on user text; without explicit propagation, routing degraded to default behavior in integration.
- Expected Impact: Correct Action mapping and risk routing in end-to-end flow, including retry behavior.
- Measured Result: Smoke runs (`python -m src.main`, `python -m src.demo_ontario_flow`) pass; CRS-type queries now resolve to Action 3 in integrated flow.
- Follow-up Actions: Integrate IntakeStateMachine into chat CLI path for full multi-turn collection before retrieval.
- Owner: Yuhan Ren

Update (Execution):
- Update Date: 2026-04-12
- Change Summary: Refactored integration routing to detect intent before retrieval, added L3 fast-fail short-circuit in orchestrator, and upgraded intent classification with typo-tolerant scoring plus a new `general` intent for broad policy-update queries.
- Why Changed: Generic policy questions were being routed through strict profile-completeness gates and surfaced data-collection behavior; L3 requests also incurred unnecessary retrieval/tool cost before refusal.
- Expected Impact: Better UX for broad informational queries, lower latency for L3 refusals, and fewer misroutes caused by rigid keyword order.
- Measured Result: Pipeline now short-circuits L3 prior to retrieval, uses intent-aware retrieval filters, and routes "latest policy" style questions into L1 general-info behavior.
- Follow-up Actions: Expand eval seeds for intent robustness (mixed intent + typo cases) and tune classifier thresholds with measured confusion matrix.
- Owner: Yuhan Ren

Update (Execution):
- Update Date: 2026-04-12
- Change Summary: Added intent confidence outputs (scores + top2), ambiguity detection with clarification-first response, and risk-route explain traces attached to `FinalAnswer`.
- Why Changed: Remaining routing errors came from mixed-intent wording and low-separation intent scores, and there was limited observability for why a risk level was chosen.
- Expected Impact: Safer handling of ambiguous asks, clearer user disambiguation path, and easier debugging of risk routing decisions.
- Measured Result: Ambiguous intent queries now return a clarification response with `intent_ambiguous=true`; L3 and non-L3 routes now expose decision steps via `risk_explain`.
- Follow-up Actions: Use confusion-matrix results to tune ambiguity threshold and reduce unnecessary clarifications.
- Owner: Yuhan Ren

Update (Execution):
- Update Date: 2026-04-12
- Change Summary: Added intent-based intake bypass in `src/app.py`. Queries classified as `qa`, `general`, or `calculate` now skip the profile-collection gate and run the pipeline immediately, suppressing the "I still need more details" prompt for factual questions.
- Why Changed: The intake state machine was blocking all first-turn queries in DATA_COLLECTION mode (profile fields missing), causing factual questions like "What is the minimum CRS score?" to receive profile-collection prompts instead of answers.
- Expected Impact: Factual and policy questions are answered on the first turn without requiring the user to provide personal information.
- Measured Result: "What is the minimum CRS score for Express Entry draws?" now routes directly to the pipeline; intake clarification only appears for eligibility/pathway queries that genuinely need profile context.
- Follow-up Actions: Monitor for edge cases where a calculate query with no profile context returns a low-quality answer due to missing fields; consider a soft prompt appended to the answer rather than a blocking gate.
- Owner: Ehraaz Atif (Integration/UX)

### D-004 Retrieval Architecture Baseline (Frozen)
  - BM25 weight: 0.6
  - Vector weight: 0.4
  - Initial retrieve top-k: 20
  - Rerank keep top-k: 5
  - Metadata filters: province/program/stream/effective_date/source_type

Update (Execution):

Update (Execution):
- Update Date: 2026-04-13
- Change Summary: Reduced Action 3/4 latency and hang risk by (1) adding LLM request timeout + fail-fast fallback in `src/llm_client.py`, (2) skipping duplicate field-extraction pass in `src/orchestrator.py` for web chat flow, and (3) adding a 60s frontend request timeout with explicit timeout error in `web/index.html`.
- Why Changed: Users reported Action 3/4 requests staying in loading state for too long with no feedback.
- Expected Impact: Faster median response for Action 3/4 and no indefinite loading when upstream LLM/network stalls.
- Measured Result: Python compile checks pass; UI now surfaces timeout errors instead of spinner lock.
- Follow-up Actions: Add lightweight latency telemetry (start/end timestamps per `/api/chat`) and a regression test for timeout-path UX.
- Owner: Ehraaz Atif (Integration/UX)

Update (Execution):
- Update Date: 2026-04-10
- Change Summary: Implemented ChromaDB vector retrieval in `src/retrieval_module.py`, blended BM25 + vector scores (0.6 / 0.4), and added explicit post-hybrid reranking.
- Why Changed: The previous retrieval path was BM25-only in practice; D-004 required hybrid retrieval and reranking for semantic recall and ranking stability.
- Expected Impact: Better semantic retrieval coverage, fewer keyword-only misses, and more consistent top-k relevance ordering.
- Measured Result: Runtime retrieval now initializes persistent Chroma index and returns hybrid-ranked results; smoke tests (`python -m src.main`, `python -m src.demo_ontario_flow`) pass after integration.
- Follow-up Actions: Add retrieval quality eval slices (keyword-vs-semantic and rerank lift), and tune reranker weights using eval outcomes.
- Owner: Yuhan Ren

Update (Execution):
- Update Date: 2026-04-12
- Change Summary: Added `src/fetch_draws_data.py` which fetches Express Entry draw results from the IRCC JSON API (`ee_rounds_4_en.json`) and injects two structured chunks into `chunks.jsonl` and ChromaDB: (1) a table of recent draw cutoffs, (2) a prose explanation of how cutoffs work.
- Why Changed: The IRCC rounds page (`ee-rounds.html`) renders CRS cutoff values via JavaScript from a separate JSON API endpoint. Static HTML scraping captured only empty `<span data-json-replace="...">` placeholders — no actual numbers were indexed. This caused the agent to have zero evidence when answering questions about draw cutoffs.
- Expected Impact: Queries about minimum/recent CRS cutoff scores now retrieve grounded evidence with specific values (e.g., 488–541 range, by draw type) and the explanation that there is no fixed minimum.
- Measured Result: ChromaDB now contains 3 draw-URL chunks. `python -m src.fetch_draws_data --offline` runs cleanly and adds 2 structured chunks to the index.
- Follow-up Actions: Schedule periodic refresh (`python -m src.fetch_draws_data`) after each IRCC draw round (~biweekly). Verify retrieved draw chunks surface in top-3 for EE-001 query after next index rebuild.
- Owner: Yuhan Ren / Chao Tang (Data Ingestion)

### D-005 Eval Gates and Priorities (Frozen)
- Date: 2026-04-07
- Owner: Team (Eval)
- Status: Frozen
- Decision:
  - Priority 1 metrics: factual accuracy >= 90%, citation correctness >= 95%
  - Safety gates: hallucination rate <= 2%, refusal compliance >= 98%
- MVP Eval Set: start with 30 seeds, then expand.
- Sub-decisions:
  - Accuracy labeling: manual gold labels.
  - Citation validation: manual URL/section check.
  - Hallucination detection: auto flag + human review.
  - Release sequence: offline -> canary -> full.
- Impact: Release criteria and daily iteration policy.
- Verification: Gate pass report attached before demo freeze.

Update (Execution):
- Update Date: 2026-04-10
- Change Summary: Added a citation-title-quality eval slice in `eval/run_eval.py` that flags low-signal `section_or_title` values using Role C normalization rules.
- Why Changed: Citation field presence alone was not sufficient to measure citation usability; low-signal titles like truncated headings can still pass field-level checks.
- Expected Impact: Better visibility into citation quality regressions and clearer quality targets for retrieval/ingestion cleanup.
- Measured Result: Post-change eval reports `8/11 passed (73%)` and a `citation_title_quality_rate` of `91%`.
- Follow-up Actions: Raise citation title quality toward parity with citation coverage and add targeted retrieval cleanup for remaining low-signal titles.
- Owner: Yuhan Ren

Update (Execution):
- Update Date: 2026-04-12
- Change Summary: Expanded eval harness with intent diagnostics: `expected_intent` checks, predicted intent details, and an intent confusion matrix summary.
- Why Changed: Intent robustness work required measurable diagnostics beyond answer-level pass/fail to validate typo/mixed/general routing behavior.
- Expected Impact: Faster threshold tuning and earlier detection of intent-regression patterns during daily integration.
- Measured Result: Eval output now includes `intent_total`, `intent_accuracy`, and `intent_confusion_matrix` in `eval/results/latest.json`.
- Follow-up Actions: Grow seed set toward 30+ with balanced intent classes and periodic manual adjudication for borderline mixed-intent prompts.
- Owner: Yuhan Ren

Update (Execution):
- Update Date: 2026-04-12
- Change Summary: (1) Fixed intent classifier precision: removed `"crs"` and `"crs score"` from `calculate` mild keywords (they are domain vocabulary, not task signals); added personal-pronoun amplifier patterns (+3.0 each) that only fire when the user refers to their own profile ("my score", "I am X years old"). (2) Split `INTENT_QA` format template into two sub-types: `factual` (direct answer + mechanism explanation, selected by default) and `document` (numbered checklist, selected when document/proof/checklist keywords are present). Format sub-selection happens at `build_answer()` time and is passed via `format_override` into `_call_llm()`. (3) Corrected `EE-001` eval label from `"calculate"` to `"qa"` — the query is factual, not a personal score calculation.
- Why Changed: Bare "crs score" keywords were boosting `calculate` score on factual questions, creating a gap ≤ 0.36 against `qa` and triggering unnecessary disambiguation prompts. Separately, all `qa`-intent queries were being forced into a document-checklist format regardless of whether the user was asking about a document or a policy fact.
- Expected Impact: Factual CRS questions ("what is the minimum/cutoff/requirement") route cleanly as `qa` with no ambiguity prompt. Personal CRS calculation queries ("I am 27...what is my score") still correctly route as `calculate`. Policy fact answers use a direct prose structure instead of a numbered document list.
- Measured Result: Intent eval 11/11 PASS. EE-001 gap=0.667, win=0.833 (was gap=0.086, ambiguous=True). CRS-001 still gap=1.000 as `calculate`.
- Follow-up Actions: Monitor `qa_document` sub-type selection accuracy for queries that mention both eligibility and documents (e.g., INT-002); adjust keyword list if misclassified.
- Owner: Ella Lu (Agent/Prompt) / Yuhan Ren

### D-006 Team Execution Mode (Frozen)
- Date: 2026-04-07
- Owner: Yuhan Ren
- Status: Frozen
- Decision: Framework-first + parallel module build + daily integration.
- Role Assignment:
  - Role A Data/Retrieval: Ella Lu
  - Role B Agent/Prompt: Keqing Wang
  - Role C Policy/Tools + Framework Owner: Yuhan Ren
  - Role D Eval/Quality: Chao Tang
  - Role E Integration/UX: Ehraaz Atif
- Impact: Work sequencing, ownership, integration cadence.
- Verification: Daily end-to-end smoke run from Apr 8 onward.

Update (Execution):
- Update Date: 2026-04-07
- Change Summary: Minimal conversational CLI path added (`python -m src.chat_cli`) and scaffold status made explicit in root README.
- Why Changed: Team needed an interactive run path for immediate manual QA and clearer handoff visibility for teammate AIs.
- Expected Impact: Faster integration feedback loop and fewer misunderstandings about scaffold maturity.
- Measured Result: Local CLI entry executes successfully; `python -m src.main` smoke check remains passing (exit code 0).
- Follow-up Actions: Replace retrieval/ingestion stubs, then validate citation-rich responses in CLI.
- Owner: Yuhan Ren (Framework), Ehraaz Atif (Integration)

### D-007 Citation Field Policy (Frozen)
- Date: 2026-04-07
- Owner: Policy + Eval
- Status: Frozen
- Decision: Every key claim must include these fields:
  - source_url
  - section_or_title
  - effective_date_or_last_updated_or_unknown
  - accessed_at (ISO timestamp)
- Rule: If effective date is not published, use last updated; if neither exists, set unknown.
- Impact: Citation format and citation correctness scoring.
- Verification: 100% required citation fields in eval outputs.

Update (Execution):
- Update Date: 2026-04-10
- Change Summary: Standardized tool evidence formatting to consume canonical `ToolResult` schema fields (`output`, `error`) and removed hard dependency on legacy Role B fields.
- Why Changed: Agent evidence formatting previously expected non-canonical fields (`status`, `output_data`, `error_msg`) which conflicted with shared schema contracts.
- Expected Impact: Prevent runtime integration errors when Role C tools begin returning `ToolResult` objects.
- Measured Result: Targeted runtime check with `ToolResult(output=..., error=None)` and `ToolResult(output=None, error=...)` succeeds in `build_answer()` path.
- Follow-up Actions: Remove temporary legacy field fallback once all modules are confirmed on canonical schema.
- Owner: Yuhan Ren

Update (Execution):
- Update Date: 2026-04-10
- Change Summary: Applied Role C citation title normalization to ingestion and retrieval output so `section_or_title` is cleaned before storage and before final citation rendering.
- Why Changed: Retrieved citations included truncated low-signal headings such as `Use the` and `Apply for the`, reducing citation quality and readability.
- Expected Impact: Cleaner citation titles and more stable section/title formatting across generated answers.
- Measured Result: Focused Ontario retrieval check no longer returns `Apply for the` as a citation title; post-change eval remains 7/11 passed (64%) with no regression in citation field coverage.
- Follow-up Actions: Add a citation-quality eval slice that flags low-signal section titles automatically.
- Owner: Yuhan Ren

### D-008 Tool Scope for MVP (Frozen)
- Date: 2026-04-07
- Owner: Policy/Tools
- Status: Frozen
- Decision: CRS calculator scope for MVP is Federal Express Entry only.
- Deferred Scope: OINP stream-specific automation post-MVP.
- Impact: Tool implementation timeline and risk control.
- Verification: Federal CRS path passes seed-tool tests.

Update (Execution):
- Update Date: 2026-04-10
- Change Summary: Implemented Federal Express Entry CRS calculator in `src/policy_tool_module.py`, added Action 1 pathway backbone content, and integrated tool dispatch into `src/orchestrator.py` for calculator and visualize flows.
- Why Changed: Role C deliverables were still stubbed, leaving calculator flows and pathway backbone content unavailable in integrated runs.
- Expected Impact: Personalized CRS estimation now uses deterministic tool logic, and Action 1 flows receive a consistent static pathway scaffold.
- Measured Result: Focused personalized CRS run returns Action 3 with tool-backed score output; `python -m src.main` smoke path passes with calculator integration.
- Follow-up Actions: Expand calculator coverage beyond single-applicant Federal EE only after MVP and add more tool-specific eval seeds.
- Owner: Yuhan Ren

### D-009 Demo Success Criteria (Frozen)
- Date: 2026-04-07
- Owner: Team
- Status: Frozen
- Decision: Demo must cover all 4 Actions end-to-end.
- Must-pass:
  - All 4 Actions runnable
  - Priority 1 metrics reported
  - Safety gate status reported
- Impact: Sprint prioritization and acceptance criteria.
- Verification: Demo rehearsal checklist signed off before Apr 14 demo.

### D-010 Current Runtime Technical Constraints (Frozen for current phase)
- Date: 2026-04-07
- Owner: Team (Framework Owner: Yuhan Ren)
- Status: Frozen (current project phase only)
- Decision:
  - Models: hosted LLM endpoint is provided using `qwen3-30b-a3b-fp8` with reasoning enabled.
  - Endpoint: `https://rsm-8430-finalproject.bjlkeng.io`
- Scope note: This is a current project constraint, not a permanent future constraint.
- Impact: Model client integration, env configuration, and runtime assumptions.
- Verification: Local scaffold can call health/inference path with configured endpoint and return a valid response.

Update (Execution):
- Update Date: 2026-04-10
- Change Summary: Unified agent LLM invocation to use project-standard `src/llm_client.py` (`generate(...)`) and D-010 env settings (`LLM_ENDPOINT`, `LLM_API_KEY`, `LLM_MODEL`).
- Why Changed: Role B module used a separate direct OpenAI client path and hardcoded model behavior, creating divergence from frozen runtime constraints.
- Expected Impact: Single runtime path for all model calls, reducing configuration drift and integration ambiguity.
- Measured Result: End-to-end flows run successfully after migration; no syntax or type errors in `src/agent_module.py`, `src/orchestrator.py`, `src/schemas.py`, `src/intake.py`.
- Follow-up Actions: Move any remaining direct client calls in other modules to `llm_client.generate()` only.
- Owner: Yuhan Ren (Framework)

---

## Execution Update Template

Copy and append this block under the relevant decision ID:

- Update Date:
- Change Summary:
- Why Changed:
- Expected Impact:
- Measured Result:
- Follow-up Actions:
- Owner:

---

### D-011 Production Hardening Architecture (Frozen)
- Date: 2026-06-12
- Owner: Team (Architecture / Platform)
- Status: Frozen
- Context: Transition from interactive MVP to a launchable, production product.
  Each pipeline step was upgraded; this entry records the cross-cutting choices.
- Decisions:
  1. Embeddings — multilingual `BAAI/bge-m3` (EN + ZH + 100+ langs), replacing
     Chroma's default English-only MiniLM. Product serves English- and
     Chinese-speaking users; bge-m3 also bridges ZH queries to the EN corpus.
     Provider is pluggable (`src/embeddings.py`): bge | openai | fake (tests).
  2. Vector store — migrate ChromaDB → Postgres + pgvector (`src/vector_store.py`).
     HNSW cosine ANN, JSONB + typed filter columns, real incremental upserts
     (ON CONFLICT) instead of full index rebuilds, durable backup/restore.
  3. Retrieval — hybrid via Reciprocal Rank Fusion of dense (pgvector) +
     full-text (Postgres tsvector), then a multilingual cross-encoder rerank
     (`BAAI/bge-reranker-v2-m3`) replacing the MVP's hand-rolled lexical rerank.
     Legacy BM25+Chroma kept as an automatic fallback during migration.
  4. Crawling — Scrapling (https://github.com/D4Vinci/Scrapling) with httpx
     fallback; trafilatura main-content extraction replacing regex tag-strip
     (kills nav/footer/boilerplate noise that polluted MVP chunks).
  5. Ingestion — structure-aware chunking WITH overlap, content-hash dedup,
     per-chunk language detection, effective-date extraction (canada.ca
     "Date modified" + meta tags) so temporal provenance is no longer "unknown",
     and richer metadata (doc_id, section hierarchy, checksum, keywords).
  6. Generation — token-budget-aware context assembly (`src/context_builder.py`):
     dedup, relevance-ordered packing, tail truncation to fit the model window.
  7. Evaluation — added retrieval metrics (Recall@k / Hit@k / MRR@k,
     `eval/retrieval_metrics.py`) and a real RAGAS-style LLM-as-judge with
     human calibration (`eval/llm_judge.py`), replacing the MVP stub.
  8. LLM — provider-agnostic via central config (`src/config.py`); course
     endpoint retained for now, swappable to OpenAI/self-hosted by env only.
  9. Platform — central typed settings, structured logging + request IDs +
     latency telemetry, liveness/readiness probes, rate limiting, gunicorn
     image with healthcheck, and CI (pgvector service + fake embeddings).
- Impact: Touches every module; preserves existing schemas/signatures
  (`retrieve`, `RetrievalRequest`, `FinalAnswer`, `ingest`).
- Verification: Retrieval metrics baseline captured (legacy backend) at
  Hit@5≈0.92 / MRR@5≈0.81 / Recall@5≈0.72 on 110 samples; re-run after the
  pgvector + bge-m3 + reranker stack is live to measure lift.
- Open decisions (deferred, owner to confirm): production LLM provider; local
  vs hosted embedding runtime at deploy time; deployment target.

Update (Execution):
- Update Date: 2026-06-12
- Change Summary: Resolved two of the three deferred decisions.
  (1) Production LLM provider: **deepseek-v4-flash-260425 via Volcengine ark**
      (`https://ark.cn-beijing.volces.com/api/v3`). Verified live through
      `src/llm_client.generate`. The provider-agnostic client + central config
      made this a pure env change (no code edits).
  (2) Deployment target: **single DigitalOcean droplet (VPS)** for the test
      environment, via docker-compose (app + pgvector). Matches the bundled
      compose; for higher availability migrate the DB to a managed Postgres.
- Bug fixed: nested settings groups (LLMSettings, etc.) did not read `.env`
  (only the top-level AppSettings did), so the deepseek switch was silently
  ignored and the app kept using the qwen3 defaults. `src/config.py` now calls
  `load_dotenv()` before instantiating settings. Defaults updated to deepseek.
- Still open: local (bge-m3) vs hosted embedding runtime on the droplet —
  depends on droplet RAM/CPU (bge-m3 + reranker need ~2-3 GB and are CPU-slow on
  small droplets). See follow-up below.
- Owner: Yuhan Ren

## Change Log

- 2026-04-07: v0.3 initialized from planning decisions and role updates.
- 2026-06-12: D-000 recorded (architecture selection: RAG vs GraphRAG vs Wiki).
- 2026-06-12: D-011 added (production hardening across all pipeline steps).
- 2026-04-07: D-010 added (current model and endpoint constraints for this phase).
- 2026-04-07: D-006 execution update added (interactive CLI path and handoff visibility upgrade).
- 2026-04-07: D-004 execution update added (Ontario retrieval process demonstration path).
- 2026-04-10: D-004 execution update added (Chroma vector retrieval + hybrid scoring + explicit reranker landed).
- 2026-04-10: D-005 execution update added (citation title quality eval slice added).
- 2026-04-10: D-003 execution update added (query text propagation into integrated risk/action routing).
- 2026-04-12: D-003 execution update added (intent confidence/ambiguity handling + risk explain traces).
- 2026-04-12: D-005 execution update added (intent eval diagnostics and confusion matrix).
- 2026-04-10: D-007 execution update added (canonical ToolResult schema alignment in evidence formatting).
- 2026-04-10: D-007 execution update added (citation title normalization applied in ingestion and retrieval).
- 2026-04-10: D-008 execution update added (Federal EE CRS calculator and pathway backbone tool integrated).
- 2026-04-10: D-010 execution update added (LLM path unified to project-standard client and env settings).
