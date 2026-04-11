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
- Owner: Yuhan Ren (Framework), Ehraaz Atif (Integration)

### D-004 Retrieval Architecture Baseline (Frozen)
- Date: 2026-04-07
- Owner: Team (Data/Retrieval)
- Status: Frozen
- Decision: Hybrid retrieval + reranker + metadata filtering.
- Baseline Parameters:
  - BM25 weight: 0.6
  - Vector weight: 0.4
  - Initial retrieve top-k: 20
  - Rerank keep top-k: 5
  - Metadata filters: province/program/stream/effective_date/source_type
- Rationale: Policy text benefits from keyword precision plus semantic recall.
- Impact: Retrieval service defaults and eval baselines.
- Verification: Factual + citation metrics improve over pure-vector baseline.

Update (Execution):
- Update Date: 2026-04-07
- Change Summary: Added a demonstrative Ontario flow implementation (ingest local chunk -> retrieve requirement section -> return citation-grounded answer).
- Why Changed: Needed a concrete handoff example so ingestion/retrieval owners can implement against an explicit process target.
- Expected Impact: Faster module onboarding and fewer interpretation gaps about retrieval behavior.
- Measured Result: Demo script path added (`python -m src.demo_ontario_flow`) with deterministic retrieval hit for OINP Masters requirement query.
- Follow-up Actions: Replace demo chunk generation with real crawling/cleaning/chunking/indexing and BM25+vector hybrid retrieval.
- Owner: Yuhan Ren (Framework), Retrieval/Ingestion owners for production replacement

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
- Owner: Yuhan Ren (Framework), Keqing Wang (Agent), Chao Tang (Eval)

### D-008 Tool Scope for MVP (Frozen)
- Date: 2026-04-07
- Owner: Policy/Tools
- Status: Frozen
- Decision: CRS calculator scope for MVP is Federal Express Entry only.
- Deferred Scope: OINP stream-specific automation post-MVP.
- Impact: Tool implementation timeline and risk control.
- Verification: Federal CRS path passes seed-tool tests.

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

## Change Log

- 2026-04-07: v0.3 initialized from planning decisions and role updates.
- 2026-04-07: D-010 added (current model and endpoint constraints for this phase).
- 2026-04-07: D-006 execution update added (interactive CLI path and handoff visibility upgrade).
- 2026-04-07: D-004 execution update added (Ontario retrieval process demonstration path).
- 2026-04-10: D-003 execution update added (query text propagation into integrated risk/action routing).
- 2026-04-10: D-007 execution update added (canonical ToolResult schema alignment in evidence formatting).
- 2026-04-10: D-010 execution update added (LLM path unified to project-standard client and env settings).
