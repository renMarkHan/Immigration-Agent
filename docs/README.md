# Docs Hub (Start Here)

Last Updated: 2026-04-07

This file explains what each document is for, when to read it, and which file is the source of truth when conflicts appear.

---

## 1) Fast Read Order (By Time)

### Tonight (kickoff)
1. `Decision-Log.md`
2. `Team-Decision-Checklist.md`
3. `Team-Workflow-and-Roles.md`
4. `AI-Assistant-Handoff.md`

### Every morning before coding
1. `Decision-Log.md` (check newest updates)
2. `Team-Workflow-and-Roles.md` (confirm your role tasks)

### Before merge / integration
1. `Decision-Log.md` (did behavior-changing decisions get recorded?)
2. `AI-Assistant-Handoff.md` (contract and scaffold expectations)

### Before demo
1. `Decision-Log.md` (frozen decisions and demo criteria)
2. `Team-Workflow-and-Roles.md` (timeline and done criteria)

---

## 2) File Purpose Matrix

| File | Purpose | When to use | Owner to update |
|------|---------|-------------|-----------------|
| `Decision-Log.md` | Master decision history and frozen rules | Any behavior/rule/threshold change | Framework Owner (Yuhan) + related role owner |
| `Team-Decision-Checklist.md` | Decision progress tracker and status board | Planning sync and blocker freeze check | Team lead + decision owners |
| `Team-Workflow-and-Roles.md` | Execution plan, role responsibilities, sprint flow | Daily execution and role handoff | Team lead / integration owner |
| `AI-Assistant-Handoff.md` | Quick context for AI assistants working on scaffold | Before any AI-generated implementation | Framework Owner |
| `Alignment.md` | Background rationale and option analysis | Reference only when revisiting old tradeoffs | Optional (usually unchanged) |

---

## 3) Source-of-Truth Priority (If docs conflict)

Use this order:
1. `Decision-Log.md` (highest priority)
2. `Team-Decision-Checklist.md`
3. `Team-Workflow-and-Roles.md`
4. `AI-Assistant-Handoff.md`
5. `Alignment.md` (reference archive)

If a conflict is found, update `Decision-Log.md` first, then sync others.

---

## 4) All-Hands Read Rule

All roles should read the same core docs:
1. Decision Log
2. Workflow
3. AI Handoff

Optional role emphasis:
1. Role D (Eval/Quality) should also check Checklist status before implementation.
2. Role C/Framework Owner should confirm cross-file consistency after decision updates.

---

## 5) Update Rules (Lightweight)

1. If code behavior changes, add/update an entry in `Decision-Log.md`.
2. If status changes (not-started -> decided -> in-progress -> verified), update checklist.
3. If responsibility or timeline changes, update workflow.

---

## 6) Recording Boundary (Very Important)

Use this rule across the team:
1. Decision Log records **why** and **what principle/rule changed**.
2. Code commits/PRs record **how the implementation changed**.

Examples:
1. "Switch retrieval default from pure vector to hybrid" -> Decision Log.
2. "Refactor retriever.py and add BM25 weighting function" -> commit/PR.
3. "Change refusal threshold and policy wording" -> Decision Log + commit/PR.

---

## 7) Practical Recommendation

Keep doc paths stable from this point forward unless a clear cleanup is required.
Use this docs hub as the navigation layer to reduce confusion.

---

## 8) Team AI Workflow (Copy and Use)

When a teammate starts a new AI session, use this flow:
1. Tell AI your role and owner name.
2. Tell AI the exact deliverable for this session.
3. Ask AI to read required docs in order.
4. Require AI to propose a short plan first.
5. Let AI implement only within your role boundary.
6. Require AI to output:
	- what changed in code
	- what must be written to Decision Log (if any)
	- suggested commit message
7. Before merge, ask AI for contract/decision consistency check.

For a copy-paste starter prompt, use `Teammate-AI-Quickstart.md`.
