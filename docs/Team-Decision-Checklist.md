# Canada Immigration & PR Navigator
## Team Decision Checklist v0.2

Date Created: 2026-04-07 | Last Updated: 2026-04-07  
Team: Team 3 (Chao Tang, Ehraaz Atif, Ella Lu, Keqing Wang, Yuhan Ren)  
Purpose: Track ownership and progress on critical decisions for team alignment

> **⚠️ TIMELINE CHANGE: MVP must ship within 1 week (by 2026-04-14).**
> - Decisions 1-5: Discuss and freeze **ALL TODAY (Apr 7)** — start writing code tomorrow morning.
> - Decisions 6-12: **Skip discussion. Apply recommended defaults now. Revisit post-MVP.**

---

## Usage Guide
- **Status**: Not Started | In Discussion | Decided | In Progress | Verified
- **Owner**: Assign all people involved in discussion/decision
- **Deadline**: 🔴 TODAY (Apr 7) = must freeze | 🟡 Post-MVP = default applied
- **Decision Summary**: Fill in chosen option and reasoning
- **Notes**: Risks, downstream impacts, dependencies

**Two types of decisions:**
- 🔴🟠 **Blockers (1-5)**: Cannot write agent code without these. Must decide before coding.
- 🟡 **Non-blockers (6-12)**: Recommended defaults applied for MVP. Revisit after launch.

---

## 🔴 BLOCKERS — Decide TODAY Before Writing Any Code (Apr 7)

### Decision 1: Refusal Policy
| Field | Content |
|-------|---------|
| **Question** | When should the agent refuse or degrade an answer? |
| **Related Section** | v0.2 Section 2.A + Section 3 (Risk Tiers) |
| **Options** | Option A (recommended): Tiered response (answer/clarify/refuse)<br/>Option B: Lenient (allow low-confidence guesses) |
| **Tradeoff** | A is safer and auditable; B faster but legal risk |
| **Recommendation** | Choose A; policy domain does not tolerate hallucination |
| **Deadline** | 🔴 2026-04-07 TODAY — blocks system prompt |
| **Owner** | Team lead + Policy/legal advisor |
| **Status** | ✅ Decided |
| **Decision Summary** | Chosen Option A (tiered response: answer / clarify / refuse). |
| **Notes** | Refusal templates provided in v0.2 Section 3; confirm final wording with product team and encode into system prompt v1. |

### Decision 2: Minimum Required Fields
| Field | Content |
|-------|---------|
| **Question** | Which fields are **required** vs **optional** in multi-turn intake? |
| **Related Section** | v0.2 Section 2.C |
| **Recommended Fields** | Age band, education, language score, current province, target province, job offer status, occupation code, graduation date |
| **Missing-field Rules** | > 2 missing: no ranking, info collection only<br/>1-2 missing: allow low-confidence pre-screening + flag missing |
| **Deadline** | 🔴 2026-04-07 TODAY — blocks intake questionnaire code |
| **Owner** | Product owner + Immigration advisor |
| **Status** | ✅ Decided |
| **Decision Summary** | Adopted recommended minimum fields and missing-field rules from v0.2 Section 2.C. |
| **Notes** | Drives v0.3 questionnaire design; affects downstream matching logic and confidence labeling. |

### Decision 3: No-Evidence Fallback Flow
| Field | Content |
|-------|---------|
| **Question** | If official evidence cannot be retrieved, should agent clarify or refuse? |
| **Related Section** | v0.2 Section 2.C4 + Section 3 (Risk Tiers) |
| **Flow Options** | Option 1: Auto-generate 1-3 clarification questions, user picks, then retry<br/>Option 2: Direct refusal + RCIC suggestion<br/>Option 3: Hybrid (depends on risk tier) |
| **Tradeoff** | 1 is friendlier but UX lag; 2 is safer but poor UX; 3 is flexible but complex |
| **Recommendation** | Choose Option 3; L1 queries clarify, L3 refuse |
| **Deadline** | 🔴 2026-04-07 TODAY — blocks state machine design |
| **Owner** | Agent owner + UX |
| **Status** | ✅ Decided |
| **Decision Summary** | Chosen Option 3 (hybrid): clarify for low/medium-risk no-evidence cases, refuse for high-risk cases. |
| **Notes** | Estimated implementation time: 0.5-1.0 day (state machine + prompt rules + tests). Must be encoded in v0.3 system prompt. |

### Decision 4: Retrieval Architecture — Decide TODAY
| Field | Content |
|-------|---------|
| **Question** | What retrieval strategy ensures accuracy and completeness for policy queries? |
| **Related Section** | v0.2 Section 2.G + Section 5 |
| **Recommended Stack** | Hybrid: BM25/keyword + vector retrieval<br/>+ Reranker for top-k refinement<br/>+ Metadata filters (province/program/effective_date) |
| **Sub-decisions** | 1. BM25 vs other keyword methods?<br/>2. Embedding model (dimension/architecture)?<br/>3. Reranker: open-source or API?<br/>4. Metadata hierarchy (program/stream/section/effective_date)? |
| **Tradeoff** | Pure vector is fast but misses keyword constraints; hybrid+rerank is more reliable |
| **Recommendation** | Hybrid + Reranker; policy QA benefits significantly |
| **Deadline** | 🔴 2026-04-07 TODAY — blocks data pipeline build |
| **Owner** | Data/Retrieval owner |
| **Status** | ✅ Decided |
| **Decision Summary** | Adopted recommended retrieval stack: hybrid BM25 + vector, reranker, metadata filters. |
| **Notes** | If unsure during implementation: start with LlamaIndex built-ins first, then optimize/customize only if evals show gaps. |

### Decision 5: Evaluation Gates and Launch Thresholds — Decide TODAY
| Field | Content |
|-------|---------|
| **Question** | What eval metrics and values are necessary for MVP launch? |
| **Related Section** | v0.2 Section 2.I |
| **Suggested Thresholds** | Priority 1 (primary): Factual accuracy >= 90%, Citation correctness >= 95%<br/>Priority 2 (safety): Hallucination rate <= 2%, Compliant refusal rate >= 98% |
| **Eval Set Size** | 120 questions (factual 40% + matching 35% + conflicts 15% + refusal 10%) |
| **Sub-decisions** | 1. Accuracy definition + labeling protocol?<br/>2. Citation check: manual URL verification?<br/>3. Hallucination detection: auto or manual?<br/>4. Release schedule: offline → canary → full timeline? |
| **Deadline** | 🔴 2026-04-07 TODAY — defines "done" for MVP |
| **Owner** | Eval owner + Labeling team |
| **Status** | ✅ Decided |
| **Decision Summary** | Team confirmed factual accuracy and citation correctness as highest priority; other two thresholds remain required safety gates. |
| **Notes** | For 1-week MVP: start with 30 seed evals. Recommended sub-decisions: manual gold labeling for accuracy, manual citation verification, hybrid hallucination detection (auto flag + human review), and staged release (offline → canary → full). |

---

## 🟡 NON-BLOCKERS — Recommended Defaults Applied for MVP (Revisit Post-Launch)

> These decisions will NOT block the MVP. The recommended default from v0.2 is in effect for each.
> After MVP ships, revisit and refine each one.

### Decision 6: Rule Version Management
| Field | Content |
|-------|---------|
| **Question** | How should scoring rules (CRS, PNP scores) be versioned and updated? |
| **Related Section** | v0.2 Section 2.E |
| **Recommended Approach** | Config-driven: YAML/JSON storage + version/effective_date/owner/source_url + runtime reads latest valid |
| **Sub-decisions** | 1. Storage location (DB/filesystem/config center)?<br/>2. Update frequency and SLA?<br/>3. Who owns rule updates?<br/>4. Diff and approval process (require regression test on change)? |
| **Deadline** | 🟡 Post-MVP |
| **Owner** | Policy owner + DevOps |
| **Status** | 🟡 Default applied: YAML/JSON config files in repo |
| **Decision Summary** | MVP default: hardcoded YAML files, manually updated |
| **Notes** | Rule updates are the most frequent ops task; good versioning prevents incidents |

### Decision 7: Action 1 Generation Method
| Field | Content |
|-------|---------|
| **Question** | Should the hierarchy tree be a static template or dynamically generated each time? |
| **Related Section** | v0.2 Section 2.B |
| **Options** | Option A (recommended): Static backbone + dynamic evidence fill<br/>Option B: Fully dynamic generation |
| **Tradeoff** | A is stable/consistent; B is flexible |
| **Recommendation** | MVP use A; incrementally add dynamic nodes later |
| **Deadline** | 🟡 Post-MVP |
| **Owner** | Agent owner + UX |
| **Status** | 🟡 Default applied: static backbone + dynamic evidence fill |
| **Decision Summary** | MVP default: static backbone (Option A) |
| **Notes** | Test static version first; upgrade to dynamic nodes post-MVP |

### Decision 8: Data Crawling and Update SLA
| Field | Content |
|-------|---------|
| **Question** | How to crawl policy data, when to update, how to ensure auditability? |
| **Related Section** | v0.2 Section 2.H |
| **Recommended Strategy** | v1: Semi-automated crawl + manual verification<br/>Incremental: URL fingerprint detects changes<br/>SLA: Target 24h, max 72h<br/>Audit: Store crawl time/source URL/snapshot version id |
| **Sub-decisions** | 1. Anti-scraping handling needed?<br/>2. Incremental vs full crawl?<br/>3. Snapshot retention window?<br/>4. Crawl ops owner? |
| **Deadline** | 🟡 Post-MVP |
| **Owner** | Data owner |
| **Status** | 🟡 Default applied: manual one-time crawl for MVP |
| **Decision Summary** | MVP default: manual download + static local repo (as noted in proposal backup plan) |
| **Notes** | Build incremental crawl after MVP ships |

### Decision 9: Document Checklist Granularity
| Field | Content |
|-------|---------|
| **Question** | Should recommended materials follow a generic template or be stream-specific? |
| **Related Section** | v0.2 Section 2.F |
| **Recommended Approach** | Two-layer: Common layer (identity/education/language/funds) + Pathway layer (stream-specific) |
| **Sub-decisions** | 1. Do all streams have significant differences?<br/>2. Output format handling (shared template or action-specific format)?<br/>3. Does each item include reason/source/alternatives? |
| **Deadline** | 🟡 Post-MVP |
| **Owner** | Policy owner + Content owner |
| **Status** | 🟡 Default applied: two-layer (common + pathway) |
| **Decision Summary** | MVP default: two-layer checklist |
| **Notes** | Start with 2-3 streams; expand post-MVP |

### Decision 10: Privacy and Data Security
| Field | Content |
|-------|---------|
| **Question** | How to collect, store, retain, and delete user data? |
| **Related Section** | v0.2 Section 2.J + Section 3 (G class) |
| **Minimum Requirements** | Data minimization<br/>Encrypt in transit and at rest<br/>Default retention 30 days (configurable)<br/>Deletion: soft delete immediate, hard delete by T+7<br/>Sensitive fields masked |
| **Sub-decisions** | 1. Collect user identity (name/email)?<br/>2. PIPEDA (Canadian privacy law) compliance review?<br/>3. Is T+7 deletion SLA realistic?<br/>4. Anonymize data for eval use? |
| **Deadline** | 🟡 Post-MVP |
| **Owner** | Legal/Privacy + System owner |
| **Status** | 🟡 Default applied: no PII storage in MVP, session data in memory only |
| **Decision Summary** | MVP default: no persistent user data stored |
| **Notes** | This is the safest MVP default; add storage + privacy policy before any real user exposure |

---

## Lower Priority (can quick-check Week 3-4)

### Decision 11: Recompute on Profile Change
| Field | Content |
|-------|---------|
| **Question** | Full recompute or partial update when user changes profile info? |
| **Related Section** | v0.2 Section 2.D |
| **Recommendation** | MVP: full recompute (Option A); stability first |
| **Deadline** | 2026-04-21 (Mon Week 4) |
| **Owner** | Agent owner |
| **Status** | 🔲 Not Started |
| **Decision Summary** | TBD |

### Decision 12: Staged Release Strategy
| Field | Content |
|-------|---------|
| **Question** | Launch MVP in one step or staged (offline → canary → full)? |
| **Related Section** | v0.2 Section 2.I |
| **Recommendation** | Three stages: offline eval (24h) → canary (10-20%, 3 days) → full |
| **Deadline** | 2026-04-21 (Mon Week 4) |
| **Owner** | Product + DevOps |
| **Status** | 🔲 Not Started |
| **Decision Summary** | TBD |

---

## Decision Summary Table (Progress Tracker)

| # | Title | Week 1 | Week 2 | Week 3-4 | Priority | Status |
|----|-------|--------|--------|----------|----------|--------|
| 1 | Refusal Policy | 🔴 Apr 7 | | | ⭐⭐⭐ | ✅ Decided |
| 2 | Min Fields | 🔴 Apr 7 | | | ⭐⭐⭐ | ✅ Decided |
| 3 | No-Evidence Flow | 🔴 Apr 7 | | | ⭐⭐⭐ | ✅ Decided |
| 4 | Retrieval Stack | 🔴 Apr 7 | | | ⭐⭐⭐ | ✅ Decided |
| 5 | Eval Thresholds | 🔴 Apr 7 | | | ⭐⭐⭐ | ✅ Decided |
| 6 | Rule Versioning | | | 🟡 Post-MVP | ⭐⭐ | 🟡 Default |
| 7 | Action 1 Gen | | | 🟡 Post-MVP | ⭐⭐ | 🟡 Default |
| 8 | Crawl & SLA | | | 🟡 Post-MVP | ⭐⭐ | 🟡 Default |
| 9 | Checklist Grain | | | 🟡 Post-MVP | ⭐ | 🟡 Default |
| 10 | Privacy | | | 🟡 Post-MVP | ⭐⭐⭐ | 🟡 Default |
| 11 | Recompute | | | 🟡 Post-MVP | ⭐ | 🟡 Default |
| 12 | Release Stage | | | 🟡 Post-MVP | ⭐⭐ | 🟡 Default |

---

## 1-Week MVP Sprint Plan

**TODAY — Apr 7 (Evening)**
- Share this checklist with full team
- Decisions 1-5 frozen: refusal policy, min fields, no-evidence flow, retrieval stack, eval thresholds
- Output: execution can start immediately (system prompt, retrieval pipeline, eval framework)

**Apr 8 (Morning — start coding, no more decisions needed)**
- All 5 decisions already frozen last night
- Output: data pipeline, system prompt, and eval framework all start in parallel

**Apr 8-9**
- Data: one-time manual crawl of IRCC + OINP pages → chunk → embed → index
- Agent: system prompt + intake questionnaire + routing logic

**Apr 10-11**
- Integration: retrieval + agent + scoring tool end-to-end
- Run 30 seed eval questions; fix critical failures

**Apr 12-13**
- Polish: output formatting, citation formatting, refusal flow testing
- Fix any hallucination failures found in seed eval

**Apr 14**
- MVP demo-ready
- Decisions 6-12: note what to improve post-demo

---

## Related Documents
- Reference: `Alignment.md`
- Original Proposal: `Final Proposal Draft.docx`
