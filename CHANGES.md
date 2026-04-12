# Canada PR Navigator — Integration & UX Change Summary

**Role E (Integration & UX) — Ehraaz Atif**  
Covers all changes made to the codebase from the initial scaffold to the final hand-in version.

---

## Overview

The initial scaffold provided working module stubs, shared schemas, a terminal CLI, and an orchestrator pipeline. The Role E contribution wired all of this into a functioning web application, then systematically identified and fixed six categories of bugs discovered during live testing.

**Files created (new):**
- `src/app.py` — Flask API server
- `web/index.html` — Web UI

**Files modified:**
- `src/agent_module.py` — Action routing and LLM call fixes
- `src/agent/system_prompt.py` — Citation and output format instruction fixes
- `src/intake.py` — Field extraction complete rewrite
- `src/ingestion_module.py` — Windows encoding fix
- `src/retrieval_module.py` — Windows encoding fix

---

## 1. New: Flask API Server (`src/app.py`)

**What the initial scaffold had:** A terminal CLI (`src/chat_cli.py`) that accepted typed input and printed raw JSON responses. No HTTP interface, no session management beyond a single `IntakeProfile` object per run.

**What was built:**

A Flask web server that wraps `IntakeStateMachine` and `run_pipeline()` behind a clean HTTP API, with in-memory session management so multiple concurrent sessions can be tracked independently.

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Serves `web/index.html` |
| `/api/session` | POST | Creates an `IntakeStateMachine` session, returns session ID and greeting |
| `/api/chat` | POST | Processes one conversation turn — collecting or full pipeline answer |
| `/api/session/<id>` | GET | Returns current session profile state |
| `/api/health` | GET | Health check |
| `/api/status` | GET | Reports whether the ChromaDB index is built and how many chunks are loaded |

**Key design decisions:**

- The `SessionStore` class holds `machine`, `session`, and `original_query` (added later — see Bug Fix #3 below) per session ID.
- The `/api/chat` endpoint distinguishes between `type: "collecting"` (intake still in progress) and `type: "answer"` (pipeline ran and returned a `FinalAnswer`). This lets the frontend render them differently.
- `_clean_answer_text()` post-processes every LLM answer before it reaches the frontend, stripping citation JSON blocks, `[LOW CONFIDENCE]` warnings, and disclaimer text that the system prompt instructed the LLM to embed inline — since all of these are already surfaced as structured fields in the API response.

---

## 2. New: Web UI (`web/index.html`)

**What the initial scaffold had:** Nothing. The only interface was the terminal CLI.

**What was built:**

A single-file web application (HTML + CSS + JS, no build step required) served by the Flask app.

**Layout:** Two-panel — chat on the left, live profile tracker on the right.

**Profile tracker (sidebar):**
- Shows all 8 required D-002 intake fields with green/grey dot indicators
- Fields fill in visibly as the user answers intake questions
- Progress bar at the bottom shows `n / 8 fields` complete
- Optional fields appear below required fields once collected

**Chat panel:**
- Welcome screen with clickable cards for all 4 Actions, so users can start from a specific intent
- Greeting card with contextual quick-fill chips (shows the next missing field's demo value as a one-click answer, updating each turn)
- **Collecting cards** (shown during intake): display a `Collecting profile — n/8 fields` header with a pulsing yellow indicator so users understand they are in intake, not being answered yet
- **Answer cards** (shown when pipeline responds): include action-type badge (Pathway Overview / Eligibility Check / CRS Calculator / Document Checklist), risk level badge (L1 / L2 / L3), the formatted answer body, and a citations section with source URL, section title, effective date, and accessed date for each citation
- Typing indicator (animated dots) while waiting for server response
- Index status banner: checks `/api/status` on page load and shows a yellow warning if the retrieval index has not been built yet, dismissing automatically after 4 seconds once the index is ready
- "↺ New conversation" button in the header to reset state without a full page reload
- Light markdown renderer: converts `**bold**`, numbered lists, and bullet lists from the LLM's output into proper HTML (the system prompt instructs the LLM to use markdown)

---

## 3. Bug Fix: Windows File Encoding (`src/ingestion_module.py`, `src/retrieval_module.py`)

**Symptom:** `'charmap' codec can't decode byte 0x9d in position 4404` when running the app on Windows after building the retrieval index.

**Root cause:** Python's `open()` defaults to the system locale codec on Windows (`cp1252` / `charmap` instead of UTF-8). Canadian government policy pages contain non-ASCII characters (curly quotes `""`, em dashes `—`, French accented characters `é`, `à`) that are valid UTF-8 but not valid `charmap`.

**Fix:** Added `encoding="utf-8"` to all four `open()` calls across both files:

| File | Line | Change |
|---|---|---|
| `retrieval_module.py` | reads `chunks.jsonl` for BM25 index | `open(..., encoding="utf-8")` |
| `ingestion_module.py` | reads existing chunks for deduplication | `open(..., encoding="utf-8")` |
| `ingestion_module.py` | writes new chunks (append mode) | `open(..., "a", encoding="utf-8")` |
| `ingestion_module.py` | reads `url_registry.json` | `open(..., encoding="utf-8")` |

---

## 4. Bug Fix: Inline Citation JSON in Answer Text (`src/app.py`, `src/agent/system_prompt.py`)

**Symptom:** Raw JSON citation objects appearing in the answer body visible to users:
```
{ "source_url": "https://canada.ca/...", "section_or_title": "Job offer", ... }
```
Also: `[LOW CONFIDENCE] 2 required field(s) are missing...` and a disclaimer sentence appearing inline in the answer text.

**Root cause (two parts):**

1. `src/agent/system_prompt.py` `_CITATION_FORMAT_REMINDER` explicitly instructed the LLM: *"After each key factual claim, insert the citation JSON block."* The LLM followed this instruction faithfully.
2. `_clean_answer_text()` in `app.py` only matched single-line JSON objects (`{ "source_url": "..." }` on one line). The LLM was emitting multi-line JSON with each key on its own line, which the cleaner's regex did not catch.

**Fix (two parts):**

1. **`src/agent/system_prompt.py`:** Replaced `_CITATION_FORMAT_REMINDER` — removed the instruction to output JSON blocks entirely. New instruction: *"Reference sources naturally in prose ('According to the IRCC page…'). Do NOT output raw JSON objects."* Also removed the instruction to append a disclaimer paragraph (the UI already appends one).  
   Updated `_OUTPUT_FORMAT` to instruct the LLM to use markdown formatting (`**bold**`, numbered lists) since the UI renders it, and removed the generic output rules that competed with per-action format instructions.

2. **`src/app.py`:** Replaced the single-line regex in `_clean_answer_text()` with a `re.DOTALL` pattern that catches multi-line blocks: `re.sub(r'\{[^{}]*?"source_url"[^{}]*?\}', '', text, flags=re.DOTALL)`.

---

## 5. Bug Fix: All Actions Routing as "Eligibility Check" (`src/app.py`, `src/agent_module.py`, `src/intake.py`)

**Symptom:** Regardless of whether the user asked "What is my CRS score?", "What documents do I need?", or "What PR pathways exist?", the response always showed the **Eligibility Check** badge and returned an eligibility-style answer.

**Root cause (two separate causes stacked together):**

**Cause A — Wrong query reaching the pipeline (`src/app.py`):**  
The user's original question (e.g. "What is my CRS score?") was asked at turn 1. But `ready_for_retrieval=True` was triggered several turns later when the user sent an intake answer like "I do not have a job offer". At that point, `session.profile.query` was set to `"I do not have a job offer"`, and `detect_intent("I do not have a job offer")` defaulted to `INTENT_MATCH` → `action_2` every time. The original question was lost.

**Cause B — Priority order in intent detection (`src/agent_module.py`, `src/intake.py`):**  
In both `detect_intent()` and `route_scene()`, the eligibility match check ran before the pathway/visualize check. The regex pattern `\bmy (eligibility|application|profile)\b` matched queries like "What PR pathways exist for someone with **my profile**?" — returning `action_2` (Eligibility Check) before the pathway keywords were ever evaluated.

**Fixes:**

**`src/app.py`:**
- Added `original_query` field to the session store dict, set to the very first message the user sends.
- On the first pipeline call (transitioning from collecting → ready), uses `original_query` instead of the current intake answer message as `session.profile.query`.
- On subsequent turns when the profile is already complete, uses the current message directly (it is the actual new question).

**`src/agent_module.py` and `src/intake.py`:**
- Moved the visualize/ACTION_1 check above the match/ACTION_2 check in both `detect_intent()` and `route_scene()`.
- Priority order changed from `calculate → qa → match → visualize` to `calculate → visualize → qa → match`.
- "pathway", "pathways", "overview" are now evaluated before `\bmy profile\b`.

---

## 6. Bug Fix: Action Instructions Ignored by LLM (`src/agent_module.py`)

**Symptom:** Even with the correct action type detected, the LLM produced similar-looking eligibility-style answers regardless of whether the question called for a CRS score breakdown, a document checklist, or a pathway overview.

**Root cause (two parts):**

1. **System prompt overrode action instructions.** The system prompt's `_OUTPUT_FORMAT` block contained generic rules (*"plain prose and numbered lists only"*, word count targets). These were in the `system` role, which the model weights more heavily than the `user` role. The per-action format instructions were appended at the bottom of the user turn — after a large evidence block — and were largely ignored.

2. **`max_tokens=1200` was too low.** qwen3-30b in reasoning mode consumes tokens on chain-of-thought before producing visible output, leaving insufficient budget to generate a properly structured response.

**Fix (`src/agent_module.py`):**

`_call_llm()` was extended to accept `intent` as a parameter. It now prepends an action-specific override block **at the very top of the system prompt**, before any other content:

```
=== ACTIVE ACTION FOR THIS TURN: ACTION 3 — CRS Score Calculation ===
You MUST structure your entire response according to these instructions
and IGNORE the generic OUTPUT FORMAT RULES below for this turn:
...
```

This ensures the model sees the specific formatting requirement as the first thing in the highest-priority context position.  
`max_tokens` raised from `1200` to `2048`.

---

## 7. Bug Fix: Field Extraction Only Capturing One Field Per Message (`src/intake.py`)

**Symptom:** Sending "I am 27 with a Master's from University of Toronto, IELTS R8 W7 L8.5 S7.5, no job offer" would only fill in one field (e.g. age), requiring the user to repeat themselves multiple times for each individual piece of information.

**Also:** Sentences containing the word "on" (e.g. "I'm **on** a student visa", "working **on** my application") incorrectly set `current_province = "Ontario"`.

**Root cause:**

The original `_extract_fields()` was a regex stub with a comment explicitly flagging it: *"This is a rule-based stub for MVP. Replace with LLM structured output before the Demo."* The regex had three specific failure modes:

1. **Province false positive:** `"on": "Ontario"` in the province map used `\bon\b` — a word-boundary match on the literal string "on", which is also one of the most common English prepositions.

2. **Education patterns too narrow:** Only matched `master`, `phd`, `bachelor`, `diploma`. Common phrasings like "graduate degree", "university degree", "postgraduate" returned nothing.

3. **The LLM extractor was silently falling back to regex due to three parsing failures:**
   - qwen3 prepends `<think>...</think>` reasoning tokens before its output; `json.loads("<think>...</think>\n{...}")` throws immediately.
   - The model sometimes adds prose preamble before the JSON ("Here are the fields: {...}"); `json.loads` on the full string fails.
   - `max_tokens=256` was too small for a reasoning model to both think and output a full JSON object; truncated JSON causes a parse error.

**Fix:**

`_extract_fields()` now calls `_extract_fields_llm()` first, with `_extract_fields_regex()` as a genuine fallback (not the silent default).

**`_extract_fields_llm()` fixes:**
- Added `re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)` before any parsing.
- Replaced `json.loads(raw)` with `re.search(r"\{.*\}", raw, re.DOTALL)` to find and parse the JSON object regardless of surrounding prose.
- Raised `max_tokens` from `256` to `512`.
- Prompt rewritten to be unambiguous: plain text field list, no conflicting quote styles, explicit "return {} if no fields present".

**`_extract_fields_regex()` fixes (fallback):**
- Removed `"on": "Ontario"` and all other two-letter province abbreviations from the province map (they matched common English words). Full province names only.
- Added a US location blocklist: if the message mentions New York, California, a US state, or "USA", province extraction is skipped entirely.
- Expanded education patterns to cover: `graduate degree`, `grad degree`, `postgraduate`, `post-graduate`, `honours degree`, `m.sc`.
- Fixed `job_offer_status` yes-detection: old pattern `\b(yes|i have)\b.{0,20}(job offer)` matched "I have **no** job offer" because `.{0,20}` bridged "have" to "job offer" through the word "no". Replaced with an explicit phrase list.

---

## Summary Table

| # | Category | Files Changed | Severity |
|---|---|---|---|
| 1 | Windows UTF-8 encoding crash | `ingestion_module.py`, `retrieval_module.py` | Critical (app unusable on Windows) |
| 2 | Citation JSON rendered in answer text | `app.py`, `system_prompt.py` | High (poor UX, confusing output) |
| 3 | All actions routing as Eligibility Check | `app.py`, `agent_module.py`, `intake.py` | High (core functionality broken) |
| 4 | LLM ignoring action-specific format | `agent_module.py` | High (all answers look the same) |
| 5 | Field extraction: only one field per message | `intake.py` | High (intake takes 8x as many turns) |
| 6 | "on" → Ontario false positive | `intake.py` | Medium (incorrect profile data) |
| — | Flask API server | `app.py` (new) | — |
| — | Web UI | `web/index.html` (new) | — |

---

## Decision Log Notes

The following changes had behavioural impact and should be noted in `docs/Decision-Log.md` under their respective decision IDs:

- **D-007 (Citation Field Policy):** The system prompt no longer instructs the LLM to emit inline JSON citation blocks. Citations are still captured and surfaced via `answer.citations[]` from retrieval metadata. The policy intent is preserved; only the LLM output mechanism changed.
- **D-010 (Runtime Constraints):** `max_tokens` raised from 1200 → 2048 for pipeline LLM calls, and from 256 → 512 for field extraction calls, to accommodate qwen3 reasoning token consumption.
- **D-003 (No-Evidence Flow):** The `original_query` fix in `app.py` is required for correct risk routing — `detect_intent()` must receive the user's actual question, not an intake answer.
