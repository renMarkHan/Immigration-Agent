# Canada Immigration & PR Navigator
## Alignment Q&A Log v0.2

Date: 2026-04-06  
Team: Team 3 (Chao Tang, Ehraaz Atif, Ella Lu, Keqing Wang, Yuhan Ren)  
Purpose: Upgrade v0.1 into an executable planning document with option templates and a refusal/risk policy.

---

## 1. Confirmed Scope (Locked)
1. Primary users: International students already in Canada.
2. Launch scope: Ontario + Federal first; expand to more provinces later.
3. Language strategy: English-only output for MVP.
4. Current priority: Answer accuracy over next-step completion.
5. Source policy: Latest official pages are the ground truth.
6. Minimum citation format: URL + section for every key claim.
7. Conflict handling: Federal/provincial conflicts must be shown explicitly.
8. Temporal handling: Expired policy is invalid; publish date vs effective date must be surfaced.
9. Recommendation explainability: Must include both recommend and non-recommend reasons.
10. Tool fallback: If calculator fails, switch to information-only mode.
11. Risk notice: In high uncertainty, recommend consulting RCIC.
12. Traceability: Log intermediate steps (retrieval evidence, tool calls, decision path).

---

## 2. v0.2 Decision Templates (Convert Open Items into Options)

### A. Refusal Policy (must finalize first)
Option A (recommended): Tiered response policy
1. Answer: Sufficient official evidence, answer with citations.
2. Clarify: Ambiguous query, ask 1-3 clarification questions.
3. Refuse: No official evidence or illegal/fraud request, refuse and provide compliant alternatives.

Option B: Lenient response
1. Return low-confidence guesses when evidence is weak.

Tradeoff
1. A is safer and auditable, slightly slower.
2. B is faster but risky for legal-domain guidance.

Recommendation: Choose Option A.

### B. Action 1 structure generation
Option A (recommended): Static backbone + dynamic evidence fill
1. Predefine a stable immigration tree (Federal/PNP/Ontario streams).
2. Fill node details dynamically from retrieval with citations.

Option B: Fully dynamic tree generation
1. Generate the whole tree directly from retrieved chunks each time.

Tradeoff
1. A is consistent and less drift-prone.
2. B is flexible but unstable in hierarchy/format.

Recommendation: Start with A.

### C. Multi-turn intake (formerly “interview”) minimum fields
Recommended minimum fields
1. Age band.
2. Highest education (Canada vs outside Canada).
3. Language test type and score (or missing marker).
4. Current province and target province.
5. Job offer status.
6. NOC/occupation category (optional but strongly recommended).
7. Graduation date (for policy windows).

Rules
1. If more than 2 required fields are missing: no ranking, only data collection + guidance.
2. If 1-2 fields are missing: allow low-confidence pre-screening with explicit missing-field warning.

### D. Recompute strategy when profile changes
Option A (recommended): Full recompute
1. Re-run eligibility filtering, scoring, and ranking end-to-end.

Option B: Partial update
1. Recompute only impacted branches.

Tradeoff
1. A is more correct for v1.
2. B is faster but can miss linked constraints.

Recommendation: Use A for v1.

### E. Score rule versioning
Option A (recommended): Config-driven version management
1. Store rule sets in YAML/JSON per stream.
2. Every change records version, effective_date, source_url, owner.
3. Runtime uses latest valid version; keep history for audit replay.

Why not hardcode
1. Policies change.
2. Config-driven updates are safer and easier for team review.

### F. Document checklist granularity
Option A (recommended): Two-layer checklist
1. Common layer: identity, education, language, funds.
2. Pathway layer: stream-specific docs and deadlines.

Output requirement
1. Every checklist item includes rationale + source section + optional alternatives.

### G. Retrieval architecture (accuracy-first)
Recommended stack
1. Hybrid retrieval: BM25/keyword + vector retrieval.
2. Reranker for top-k refinement in policy QA.
3. Metadata filtering by province/program/stream/effective_date/source_type.

Tradeoff
1. Pure vector is simpler but may miss keyword constraints.
2. Hybrid+rereank costs more but is more reliable for legal/policy text.

### H. Crawling and freshness
Recommended strategy
1. v1: semi-automated crawl + manual verification.
2. Incremental update by URL fingerprint/hash.
3. Freshness SLA: target 24h, max 72h.
4. Auditability: store crawl timestamp, source URL, snapshot version id.

### I. Evaluation and launch gates (v1)
Offline eval set suggestion
1. Start with 120 questions.
2. Distribution: factual QA 40%, eligibility matching 35%, policy conflicts 15%, refusal/sensitive 10%.

Launch thresholds
1. Factual accuracy >= 90%.
2. Citation correctness >= 95%.
3. Hallucination rate <= 2%.
4. Compliant refusal rate for no-evidence cases >= 98%.

Release stages
1. Stage 1: Offline evaluation.
2. Stage 2: Canary rollout (10-20%).
3. Stage 3: Full rollout.

### J. Safety and privacy baseline
Minimum requirements
1. Data minimization for sensitive fields.
2. Encryption in transit and at rest.
3. Default retention 30 days (configurable).
4. Deletion request handling: soft delete immediate, hard delete by T+7.
5. Mandatory RCIC suggestion in high-risk uncertainty.

---

## 3. Refusal and Risk-Tier Policy (Implementation-Ready)

### Risk levels
1. L1 Low risk: factual query with clear official evidence.
2. L2 Medium risk: multi-rule composition with interpretation space.
3. L3 High risk: legal consequence claims, guarantee requests, fraud/abuse intent, or no evidence.

### Response policy
1. L1: direct answer + URL + section + effective date.
2. L2: conditional answer + uncertainty notice + follow-up questions.
3. L3: refuse deterministic conclusion + compliant alternatives + RCIC suggestion.

### Mandatory refusal cases
1. Fabrication/fraud/illegal evasion guidance.
2. Requests for guaranteed approval outcomes.
3. Requests requiring conclusions without official evidence.

### Standard refusal templates (EN)
1. Compliance refusal:
"I cannot provide guidance that violates laws or enables fraud. I can help you follow the official legal process with traceable sources."
2. Evidence insufficiency refusal:
"I do not currently have sufficient official evidence to support a definitive conclusion. To avoid misinformation, I will not make a guess. Please share more specifics (province, stream, timeline) and I can continue with targeted retrieval."

---

## 4. Traceability Logging Schema (recommended)
1. session_id
2. user_query
3. normalized_intent
4. collected_profile_fields
5. retrieval_queries
6. retrieved_sources (url, section, effective_date, snippet_hash)
7. tool_calls (name, input, output, status, latency_ms)
8. decision_type (answer/clarify/refuse/degrade)
9. final_answer_citations
10. risk_level
11. model_version
12. timestamp

---

## 5. Suggested Team Ownership
1. Data owner: crawling, cleaning, freshness, source allowlist.
2. Retrieval owner: chunking, hybrid search, reranker, metadata filters.
3. Policy owner: score configs, versioning, effective-date validation.
4. Agent owner: dialogue state, routing, refusal policy, tool orchestration.
5. Eval owner: benchmark set, scorecards, regression tests.

---

## 6. v0.3 Deliverables (next)
1. Minimum intake questionnaire.
2. System prompt v1 (safety + citation constraints).
3. Scoring tool input/output schema.
4. 120-item offline evaluation template.
5. Canary launch checklist.
