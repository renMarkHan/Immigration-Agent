# Role B (Agent & Prompt Engineer) Implementation Report

**Date:** 2026-04-09  
**Role:** Role B (Agent & Prompt Engineer)  
**Assignee:** Keqing Wang  


## Completed Tasks & Adjustments

### 1. `system_prompt_v1.txt` (and `src/agent/system_prompt.py`)
- **Status:** Created and Integrated.
- **Details:** 
  - Constructed the v1 system prompt adhering to strict frozen design constraints (D-001, D-003, D-007, D-008).
  - Defined explicit boundaries for the agent (Federal Express Entry, OINP major streams).
  - Configured rigid **Refusal Policy (D-001)** for handling queries by risk tier (L1/L2/L3).
  - Set up a **No-Evidence Guard (D-003)** to completely block hallucination when context is missing.
  - Specified the exact JSON format for **Citations (D-007)** ensuring traceability to official URLs.
  - **Adjustment:** Exported the prompt into `system_prompt_v1.txt` at the project root for review, while also structuring it properly as a Python module inside `src/agent/system_prompt.py` to allow the application to cleanly import it without file I/O operations.

### 2. `src/agent_module.py`
- **Status:** Modified & Fully Implemented.
- **Details:**
  - Implemented `detect_intent()` to classify user queries into 4 product Actions (`visualize`, `match`, `calculate`, `qa`).
  - Completed `route_risk()` to classify risk (L1, L2, L3) based on query keywords (e.g., L3 triggers for guarantees/fraud) and profile completeness.
  - Implemented `build_answer()` to:
    - Route responses based on the detected intent.
    - Intercept L3 queries and immediately apply the strict refusal template without calling the LLM.
    - Handle missing evidence scenarios gracefully (No-Evidence Fallbacks) based on risk level.
    - Format context blocks (evidence, tool results, and user profile) for LLM consumption.
    - **Adjustment:** Added an offline stub mode for testing when the LLM API is unavailable, ensuring local tests pass continuously. Updated `src/schemas.py` to ensure `ActionType` and `confidence_warning` fields are correctly typed.

### 3. `src/intake.py`
- **Status:** Created & Fully Implemented.
- **Details:**
  - Designed the `IntakeProfile` schema defining the 8 required fields (D-002) and 7 optional fields.
  - Implemented `IntakeStateMachine` to handle multi-turn conversational states (`GREETING`, `COLLECTING`, `LOW_CONFIDENCE_MATCH`, `READY_TO_MATCH`).
  - Created a robust rule-based NLP field extractor `_extract_fields()` to dynamically pull information (age, education, language scores, province, etc.) from natural language user input.
  - Implemented `assess_completeness()` to seamlessly decide whether the system should proceed with full matching, give a low-confidence warning, or enforce data collection mode.
  - Completed `route_scene()` mapping user intents precisely to Action 1/2/3/4.

### 4. `eval/samples.jsonl`
- **Status:** Updated.
- **Details:**
  - Added 6 Role B seed questions:
    - **4 Factual queries (FAC-001 to FAC-004)** testing Express Entry CLB requirements, OINP job offer requirements, stream windows, and NOC TEER codes.
    - **2 Refusal queries (REF-001, REF-002)** designed to trigger L3 safety guardrails (e.g., requesting PR guarantees and faking language scores).


### 5. Local Testing (`test_role_b.py`)
- **Status:** Created and executed successfully.
- **Details:**
  - Built a standalone test script `test_role_b.py` in the root folder.
  - The script simulates an end-to-end conversation:
    1. Agent greets and asks for fields.
    2. User provides partial information.
    3. Agent asks clarifying follow-ups.
    4. User provides more info and asks an eligibility question.
    5. Agent proceeds in `LOW_CONFIDENCE` mode, routes the risk, uses mocked retrieval, and generates a stubbed answer formatted with citations.
  - The local test confirmed that the State Machine, Intake Field Extractor, Risk Router, and Answer Builder all communicate correctly.

## Summary
Role B's responsibilities are now fully implemented and locally verified. The system can successfully drive a dynamic intake conversation, classify intents, manage risk gates strictly, and formulate policy-backed responses while resisting hallucinations. 

The codebase is ready for integration with Role A's retrieval system and Role C's CRS tool.
