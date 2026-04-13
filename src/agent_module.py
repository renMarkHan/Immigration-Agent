"""
src/agent_module.py — Risk Routing, Intent Detection & Answer Generation
Canada Immigration & PR Navigator Agent

Owner:   Keqing Wang (Role B — Agent/Prompt Engineer)
Version: v2.0
Date:    2026-04-08

─────────────────────────────────────────────────────────────────────────────
RESPONSIBILITY OF THIS FILE (agent_module.py)
─────────────────────────────────────────────────────────────────────────────
  This file contains exactly 3 public functions (+ private helpers):

  1. route_risk()     — Determine L1/L2/L3 risk level for a query turn
  2. build_answer()   — Build LLM prompt, call LLM, return FinalAnswer
                        Internally calls detect_intent() to choose Action format
  3. detect_intent()  — NEW: Classify user query → "visualize" / "match" /
                        "qa" / "calculate" (maps to Action 1/2/3/4)

  Calling order:
    route_risk()
        ↓ returns RiskLevel
    build_answer()
        ↓ internally calls
        detect_intent()
            ↓ returns intent string
        ↓ branches on intent to format response
    returns FinalAnswer

─────────────────────────────────────────────────────────────────────────────
DIVISION OF RESPONSIBILITY (do NOT duplicate logic across files)
─────────────────────────────────────────────────────────────────────────────

  intake.py  (Keqing Wang)
  ├── IntakeProfile schema + D-002 completeness rules
  ├── Multi-turn dialog state machine (GREETING → READY_TO_MATCH)
  ├── Clarification question generation
  ├── Field extraction from free text
  └── route_scene() → Action 1/2/3/4 scene routing

  agent_module.py  (THIS FILE)
  ├── detect_intent()  → intent string for answer formatting
  ├── route_risk()     → L1/L2/L3 risk level
  └── build_answer()   → LLM call + D-007 citation injection + no-evidence fallback

  schemas.py  (Yuhan Ren — Framework Owner)
  └── Canonical definitions: IntakeProfile, Citation, RetrievalResult,
      ToolResult, FinalAnswer, RiskLevel, NoEvidenceAction, ActionType

─────────────────────────────────────────────────────────────────────────────
DO NOT change function signatures without updating orchestrator.py.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, Optional

from src.schemas import (
    ActionType,
    Citation,
    FinalAnswer,
    IntakeProfile,
    NoEvidenceAction,
    RetrievalResult,
    RiskLevel,
    ToolResult,
)
from src.intake import (
    assess_completeness,
    IntakeMode,
    profile_to_context,
    build_empty_profile,
    update_profile,
    REQUIRED_FIELDS,
)
from src.agent.system_prompt import (
    get_system_prompt,
    get_l3_refusal,
)
from src.llm_client import generate


# ---------------------------------------------------------------------------
# LLM availability check (D-010 runtime settings)
# ---------------------------------------------------------------------------
def _llm_configured() -> bool:
    try:
        import os

        return bool(os.environ.get("LLM_API_KEY") and os.environ.get("LLM_ENDPOINT"))
    except Exception:
        return False


# ===========================================================================
# Intent labels (returned by detect_intent)
# ===========================================================================

INTENT_VISUALIZE  = "visualize"   # Action 1 — pathway overview / visualisation
INTENT_MATCH      = "match"       # Action 2 — eligibility matching
INTENT_CALCULATE  = "calculate"   # Action 3 — CRS score calculation
INTENT_QA         = "qa"          # Action 4 — document checklist / Q&A
INTENT_GENERAL    = "general"     # General policy updates / broad informational query

# Maps intent string → ActionType enum (for FinalAnswer)
_INTENT_TO_ACTION: dict[str, ActionType] = {
    INTENT_VISUALIZE: ActionType.ACTION_1,
    INTENT_MATCH:     ActionType.ACTION_2,
    INTENT_CALCULATE: ActionType.ACTION_3,
    INTENT_QA:        ActionType.ACTION_4,
    INTENT_GENERAL:   ActionType.ACTION_4,
}

# Action-specific response format instructions injected into LLM prompt
_ACTION_FORMAT: dict[str, str] = {
    INTENT_VISUALIZE: (
        "Structure your response as a pathway overview:\n"
        "1. List all applicable Federal pathways (FSW / CEC / FSTP) with one-line summaries.\n"
        "2. List all applicable Ontario PNP streams with one-line summaries.\n"
        "3. For each pathway, state the single most important eligibility requirement.\n"
        "4. End with a recommendation of the top 1-2 pathways for this user's profile.\n"
        "Cite the official source URL for each pathway."
    ),
    INTENT_MATCH: (
        "Structure your response as an eligibility assessment:\n"
        "1. State clearly: LIKELY ELIGIBLE / LIKELY NOT ELIGIBLE / INSUFFICIENT INFORMATION.\n"
        "2. List each key requirement and whether the user meets it (YES / NO / UNKNOWN).\n"
        "3. Identify any disqualifying factors explicitly.\n"
        "4. If eligible, state the next step the user should take.\n"
        "5. Cite the official source URL for every requirement mentioned."
    ),
    INTENT_CALCULATE: (
        "Structure your response as a CRS score breakdown:\n"
        "1. Show the score for each factor: Core Human Capital, Spouse, "
        "Skill Transferability, Additional Points.\n"
        "2. Show the total estimated CRS score.\n"
        "3. Compare to the most recent draw cutoff score (if available in evidence).\n"
        "4. Suggest 1-2 ways the user could increase their score.\n"
        "5. Cite the official CRS grid URL."
    ),
    # INTENT_QA has two sub-formats selected at runtime in build_answer():
    # - INTENT_QA (factual): for yes/no, minimum/maximum, threshold questions
    # - INTENT_QA (document): for document/checklist questions
    INTENT_QA: (
        "Structure your response as a direct factual answer:\n"
        "1. Answer the question directly in 1-2 sentences at the top.\n"
        "2. Provide supporting detail: thresholds, rules, conditions, or context.\n"
        "3. If the value varies (e.g. draw cutoffs change each round), explain the mechanism and give a realistic recent range.\n"
        "4. State what the user should do if the value changes or they need the latest figure.\n"
        "5. Cite the official source URL."
    ),
    "qa_document": (
        "Structure your response as a document checklist / Q&A answer:\n"
        "1. List all required documents in a numbered checklist.\n"
        "2. For each document: what it is, where to get it, format requirements.\n"
        "3. Separate into: Common Documents and Stream-Specific Documents.\n"
        "4. Flag any documents with long processing times (e.g. police certificates).\n"
        "5. Cite the official source URL for the checklist."
    ),
    INTENT_GENERAL: (
        "Structure your response as a policy update brief:\n"
        "1. Start with a concise summary of the latest official policy information found in evidence.\n"
        "2. Use 3-5 bullet points for major changes, dates, and affected groups.\n"
        "3. Clearly separate confirmed facts from unknown/not-found items.\n"
        "4. End with what the user should verify next on official pages.\n"
        "5. Cite the official source URL for each major point."
    ),
}

# No-evidence fallback messages
_NO_EVIDENCE_MESSAGES: dict[RiskLevel, str] = {
    RiskLevel.L1: (
        "I was not able to find specific official policy text to answer your question. "
        "Could you provide more context — for example, the specific province, stream, "
        "or timeline you are asking about? This will help me search more precisely."
    ),
    RiskLevel.L2: (
        "I do not currently have sufficient official evidence to support a definitive "
        "eligibility assessment. To avoid giving you inaccurate guidance, I will not "
        "make a guess. Please share more specifics (province, stream, graduation date) "
        "and I will retry the search. If the issue persists, I recommend consulting "
        "the official IRCC website: "
        "https://www.canada.ca/en/immigration-refugees-citizenship.html"
    ),
    RiskLevel.L3: get_l3_refusal(),
}

# L3 trigger patterns (safety gate — always refuse)
_L3_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bguarantee\b.{0,30}\b(pr|ita|approval|visa|status)\b",
        r"\b(fake|forged?|falsif|fraudulent|counterfeit)\b.{0,30}"
        r"\b(document|certificate|ielts|degree|diploma)\b",
        r"\b(buy|purchase|get).{0,20}\b(fake|false|forged?)\b",
        r"\billegal(ly)?\b.{0,30}\b(immigrat|stay|work|visa)\b",
        r"\bbypass\b.{0,30}\b(immigrat|requirement|test|exam)\b",
        r"\bcheat\b.{0,30}\b(ielts|celpip|tef|tcf|test|exam)\b",
        r"\bbribe\b",
        r"\bguarantee.{0,20}(approval|ita|invitation)\b",
        r"\b(promise|assure).{0,20}(i will get|i'll get|you will get)\b",
    ]
]


def is_l3_query(user_text: str) -> bool:
    """Return True if the query matches any high-risk refusal pattern."""
    if not user_text:
        return False
    return any(pattern.search(user_text) for pattern in _L3_PATTERNS)


def _fuzzy_contains(tokens: list[str], candidates: list[str], threshold: float = 0.86) -> bool:
    """Light typo tolerance for short keyword cues."""
    for token in tokens:
        for candidate in candidates:
            if SequenceMatcher(a=token, b=candidate).ratio() >= threshold:
                return True
    return False


def _normalize_intent_scores(score: dict[str, float]) -> dict[str, float]:
    total = sum(max(v, 0.0) for v in score.values())
    if total <= 0:
        n = float(len(score) or 1)
        return {k: 1.0 / n for k in score}
    return {k: max(v, 0.0) / total for k, v in score.items()}


def detect_intent_with_confidence(user_text: str) -> tuple[str, dict[str, float], list[str], bool]:
    """Return winner intent + normalized scores + top2 + ambiguity flag."""
    text_lower = user_text.lower().strip()
    tokens = re.findall(r"[a-z0-9]+", text_lower)

    score: dict[str, float] = {
        INTENT_CALCULATE: 0.0,
        INTENT_QA: 0.0,
        INTENT_MATCH: 0.0,
        INTENT_VISUALIZE: 0.0,
        INTENT_GENERAL: 0.0,
    }

    # Strong unambiguous calculate signals (explicit calculation request)
    calculate_strong_keywords = [
        "score breakdown", "comprehensive ranking",
        "calculate", "calculator", "how many points",
    ]
    for kw in calculate_strong_keywords:
        if kw in text_lower:
            score[INTENT_CALCULATE] += 3.0
    if _fuzzy_contains(tokens, ["calculate", "calculator"]):
        score[INTENT_CALCULATE] += 3.0

    # Weak calculate signals — only decisive when combined with personal context
    calculate_mild_keywords = ["points"]  # 'crs'/'crs score' are domain words, not calculation signals
    for kw in calculate_mild_keywords:
        if kw in text_lower:
            score[INTENT_CALCULATE] += 0.8
    if _fuzzy_contains(tokens, ["score", "points"]):  # exclude 'crs' — not a calc signal alone
        score[INTENT_CALCULATE] += 0.5

    # Personal-context amplifier: boosts calculate when user refers to their own profile
    personal_calculate_patterns = [
        r"\bmy\s+(?:crs|score|points)\b",
        r"\b(?:crs|score|points)\b.*\bmy\b",
        r"\bwhat\s+(?:is|would\s+be|will\s+be|are)\s+my\b",
        r"\b(?:i\s+am|i\s+have|i'm|i've|i\s+hold)\b",
        r"\bwith\s+(?:my|a)\s+(?:age|degree|master|bachelor|diploma|experience|ielts|clb)\b",
    ]
    for pat in personal_calculate_patterns:
        if re.search(pat, text_lower):
            score[INTENT_CALCULATE] += 3.0

    qa_keywords = [
        "document", "documents", "checklist", "what do i need",
        "what to submit", "required documents", "supporting documents",
        "proof of", "evidence of", "requirement", "minimum", "maximum",
        "require", "required",  # factual yes/no questions: "does X require Y?"
    ]
    for kw in qa_keywords:
        if kw in text_lower:
            score[INTENT_QA] += 2.5
    if _fuzzy_contains(tokens, ["document", "checklist", "requirement"]):
        score[INTENT_QA] += 1.2

    match_patterns = [
        r"\beligib",
        r"\bqualif",
        r"\bcan i (apply|get|receive)\b",
        r"\bdo i (meet|qualify|have enough)\b",
        r"\bam i (eligible|able to)\b",
        r"\bwould i (qualify|be eligible)\b",
        r"\bmy (eligibility|application|profile)\b",
    ]
    for pattern in match_patterns:
        if re.search(pattern, user_text, re.IGNORECASE):
            score[INTENT_MATCH] += 3.0

    visualize_keywords = [
        "pathway", "pathways", "options", "routes", "ways to get pr",
        "how to get pr", "what programs", "which programs", "overview",
        "what streams", "which streams", "compare",
    ]
    for kw in visualize_keywords:
        if kw in text_lower:
            score[INTENT_VISUALIZE] += 2.8
    if _fuzzy_contains(tokens, ["pathway", "programs", "options"]):
        score[INTENT_VISUALIZE] += 1.0

    general_keywords = [
        "latest immigration policy", "latest policy", "policy update",
        "policy changes", "new rules", "recent changes", "latest immigration news",
    ]
    for kw in general_keywords:
        if kw in text_lower:
            score[INTENT_GENERAL] += 3.2
    if _fuzzy_contains(tokens, ["latest", "recent", "policy", "update", "changes"]):
        score[INTENT_GENERAL] += 1.0

    norm = _normalize_intent_scores(score)
    ranked = sorted(norm.items(), key=lambda x: x[1], reverse=True)
    winner = ranked[0][0]
    top2 = [item[0] for item in ranked[:2]]
    # Ambiguous when top-2 are close and winner confidence is modest.
    ambiguous = len(ranked) > 1 and (ranked[0][1] - ranked[1][1] <= 0.36) and ranked[0][1] < 0.75
    return winner, norm, top2, ambiguous


def build_intent_clarification(top2: list[str]) -> str:
    """Return a compact disambiguation question for ambiguous intent."""
    labels = {
        INTENT_VISUALIZE: "pathway overview",
        INTENT_MATCH: "eligibility check",
        INTENT_CALCULATE: "CRS score calculation",
        INTENT_QA: "document/factual Q&A",
        INTENT_GENERAL: "latest policy update",
    }
    if len(top2) >= 2:
        a, b = labels.get(top2[0], top2[0]), labels.get(top2[1], top2[1])
        return (
            "I can help, but your request could mean two different tasks. "
            f"Do you want a {a} or a {b}?"
        )
    return "I can help. Could you clarify whether you want eligibility checking, calculation, or a policy overview?"


# ===========================================================================
# PUBLIC FUNCTION 1 — detect_intent()   [NEW]
# ===========================================================================

def detect_intent(user_text: str) -> str:
    """Identify user intent and return the corresponding intent string.

        Returns one of five intent labels:
      "visualize"  → Action 1: pathway overview / visualisation
      "match"      → Action 2: eligibility matching
      "calculate"  → Action 3: CRS score calculation
      "qa"         → Action 4: document checklist / factual Q&A
            "general"    → Action 4: broad policy updates / general informational query

    This function is called internally by build_answer() to select the
    correct response format template.

    Args:
        user_text: Raw user message.

    Returns:
        Intent string: "visualize" | "match" | "calculate" | "qa" | "general"

    Examples:
        >>> detect_intent("What is my CRS score?")
        'calculate'

        >>> detect_intent("Am I eligible for OINP Masters?")
        'match'

        >>> detect_intent("What documents do I need?")
        'qa'

        >>> detect_intent("What PR pathways exist for me?")
        'visualize'
    """
    winner, _, _, _ = detect_intent_with_confidence(user_text)
    return winner


# ===========================================================================
# PUBLIC FUNCTION 2 — route_risk()   [FILLED]
# ===========================================================================

def route_risk(
    profile: IntakeProfile,
    results: list[RetrievalResult],
    user_text: str = "",
) -> RiskLevel:
    """Determine the final risk level for this query turn.

    D-003: Classify query risk level.
      L1 — general info / factual; no personal advice needed
      L2 — personalised eligibility matching; low-to-medium stakes
      L3 — high-stakes: legal guarantees, fraud, or no evidence after retry

    Logic (in priority order):
      1. L3 safety gate: if query contains L3 signals → always return L3
      2. Profile completeness gate: if DATA_COLLECTION mode (>2 fields missing)
         → return L1 (cannot do eligibility matching yet)
      3. Intent-based classification:
         - "calculate" or "qa"  → L1 (factual / tool-based)
         - "match" or "visualize" → L2 (eligibility / personalised)
      4. No-evidence escalation: L2 + no retrieval results → escalate to L3
         (prevents LLM from hallucinating eligibility conclusions)

    NOTE: This function sets the risk label for build_answer().
    Retry/clarify/refuse dialog routing lives in intake.IntakeStateMachine.

    Args:
        profile:    Current IntakeProfile (used to check completeness mode).
        results:    Retrieval results for this query (may be empty list).
        user_text:  User's query text (used for L3 safety gate + intent).

    Returns:
        RiskLevel: L1 | L2 | L3
    """
    # ── 1. L3 safety gate ────────────────────────────────────────────────────
    level, _ = route_risk_with_explain(profile, results, user_text=user_text)
    return level


def route_risk_with_explain(
    profile: IntakeProfile,
    results: list[RetrievalResult],
    user_text: str = "",
) -> tuple[RiskLevel, dict[str, Any]]:
    """Risk routing with explicit decision trace for debugging/observability."""
    explain: dict[str, Any] = {
        "input": {
            "query": user_text,
            "results_count": len(results),
        },
        "steps": [],
        "decision": None,
    }

    if is_l3_query(user_text):
        explain["steps"].append({"gate": "l3_pattern", "matched": True})
        explain["decision"] = "L3"
        return RiskLevel.L3, explain
    explain["steps"].append({"gate": "l3_pattern", "matched": False})

    # ── 2. Intent-based baseline ─────────────────────────────────────────────
    if user_text:
        intent, intent_scores, top2, ambiguous = detect_intent_with_confidence(user_text)
    else:
        intent, intent_scores, top2, ambiguous = INTENT_GENERAL, {INTENT_GENERAL: 1.0}, [INTENT_GENERAL], False
    explain["steps"].append(
        {
            "gate": "intent_baseline",
            "intent": intent,
            "intent_scores": intent_scores,
            "intent_top2": top2,
            "ambiguous": ambiguous,
        }
    )

    if intent in (INTENT_CALCULATE, INTENT_QA, INTENT_GENERAL):
        base_level = RiskLevel.L1
    else:
        base_level = RiskLevel.L2  # match / visualize

    # ── 3. Completeness gate (only for personalised matching-like intents) ─
    completeness = assess_completeness(profile)
    if base_level == RiskLevel.L2 and completeness.mode == IntakeMode.DATA_COLLECTION:
        # Cannot do eligibility matching; treat as general info
        explain["steps"].append(
            {
                "gate": "completeness",
                "mode": completeness.mode,
                "missing_required": completeness.missing_required,
                "downgrade": "L2->L1",
            }
        )
        explain["decision"] = "L1"
        return RiskLevel.L1, explain
    explain["steps"].append(
        {
            "gate": "completeness",
            "mode": completeness.mode,
            "missing_required": completeness.missing_required,
        }
    )

    # ── 4. No-evidence escalation ────────────────────────────────────────────
    if base_level == RiskLevel.L2 and not results:
        explain["steps"].append({"gate": "no_evidence_escalation", "triggered": True, "from": "L2", "to": "L3"})
        explain["decision"] = "L3"
        return RiskLevel.L3, explain

    explain["steps"].append({"gate": "no_evidence_escalation", "triggered": False})
    explain["decision"] = str(base_level)
    return base_level, explain


# ===========================================================================
# PUBLIC FUNCTION 3 — build_answer()   [FILLED]
# ===========================================================================

def build_answer(
    profile: IntakeProfile,
    results: list[RetrievalResult],
    tool_results: list[ToolResult],
    risk_level: RiskLevel,
    retry_count: int = 0,
    user_text: str = "",
    action_type: Optional[ActionType] = None,
    risk_explain: dict[str, Any] | None = None,
    intent_scores: dict[str, float] | None = None,
    intent_top2: list[str] | None = None,
    intent_ambiguous: bool = False,
) -> FinalAnswer:
    """Construct LLM prompt, call LLM, parse and return FinalAnswer.

    Internally calls detect_intent() to determine the response format.

    Calling order:
        build_answer()
            ↓ calls
            detect_intent(user_text)
                ↓ returns "visualize" | "match" | "calculate" | "qa"
            ↓ selects format template from _ACTION_FORMAT
            ↓ calls LLM (or stub if unavailable)
        returns FinalAnswer

    D-003 no-evidence fallback:
      - No results + L1 → NoEvidenceAction.CITE_GAP   (ask for more detail)
      - No results + L2 → NoEvidenceAction.PARTIAL_ANSWER  (caveat + alternatives)
      - No results + L3 → NoEvidenceAction.REFUSE     (hard refusal, no LLM call)
    Max 1 retry allowed (retry_count <= 1).

    D-007 citation requirement:
      All key claims must include Citation objects with four fields:
        source_url, section_or_title,
        effective_date_or_last_updated_or_unknown, accessed_at.

    Args:
        profile:      Current IntakeProfile for context injection.
        results:      Retrieved policy chunks (may be empty).
        tool_results: Policy tool outputs (e.g. CRS calculator result).
        risk_level:   Risk level from route_risk().
        retry_count:  Number of retrieval retries already used (0 or 1).
        user_text:    Original user query.
        action_type:  Override action type (optional; auto-detected if None).

    Returns:
        FinalAnswer with answer text, citations, risk level, and action type.
    """
    # ── Step 1: Detect intent → select action type ───────────────────────────
    if user_text:
        intent = detect_intent(user_text)
    else:
        intent = INTENT_MATCH  # safe default

    # Allow explicit override (e.g. from orchestrator)
    if action_type is None:
        action_type = _INTENT_TO_ACTION.get(intent, ActionType.ACTION_2)

    # ── Step 2: L3 → immediate refusal, do NOT call LLM ─────────────────────
    if risk_level == RiskLevel.L3:
        return FinalAnswer(
            answer=get_l3_refusal(),
            risk_level=RiskLevel.L3,
            action_type=action_type,
            citations=[],
            no_evidence_action=NoEvidenceAction.REFUSE,
            retry_count=retry_count,
            risk_explain=risk_explain,
            intent_scores=intent_scores,
            intent_top2=intent_top2,
            intent_ambiguous=intent_ambiguous,
        )

    # ── Step 3: No evidence → tier-specific fallback ─────────────────────────
    if not results:
        if risk_level == RiskLevel.L1:
            return FinalAnswer(
                answer=_NO_EVIDENCE_MESSAGES[RiskLevel.L1],
                risk_level=RiskLevel.L1,
                action_type=action_type,
                citations=[],
                no_evidence_action=NoEvidenceAction.CITE_GAP,
                retry_count=retry_count,
                risk_explain=risk_explain,
                intent_scores=intent_scores,
                intent_top2=intent_top2,
                intent_ambiguous=intent_ambiguous,
            )
        else:  # L2 with no evidence
            return FinalAnswer(
                answer=_NO_EVIDENCE_MESSAGES[RiskLevel.L2],
                risk_level=RiskLevel.L2,
                action_type=action_type,
                citations=[],
                no_evidence_action=NoEvidenceAction.PARTIAL_ANSWER,
                retry_count=retry_count,
                risk_explain=risk_explain,
                intent_scores=intent_scores,
                intent_top2=intent_top2,
                intent_ambiguous=intent_ambiguous,
            )

    # ── Step 4: Evidence available → build LLM prompt ────────────────────────
    completeness = assess_completeness(profile)
    confidence_warning = completeness.confidence_warning

    evidence_block = _format_evidence_block(results, tool_results)
    profile_block  = profile_to_context(profile)

    # Select format instructions based on detected intent.
    # For INTENT_QA, sub-select between factual Q&A and document checklist.
    if intent == INTENT_QA:
        _doc_keywords = ["document", "documents", "checklist", "what do i need",
                         "what to submit", "required documents", "supporting documents",
                         "proof of", "evidence of"]
        _is_doc_qa = any(kw in user_text.lower() for kw in _doc_keywords)
        format_instructions = _ACTION_FORMAT["qa_document" if _is_doc_qa else INTENT_QA]
    else:
        format_instructions = _ACTION_FORMAT.get(intent, _ACTION_FORMAT[INTENT_MATCH])

    user_turn = (
        f"USER QUERY:\n{user_text}\n\n"
        f"{profile_block}\n\n"
        f"RETRIEVED POLICY EVIDENCE:\n{evidence_block}\n\n"
        f"RESPONSE FORMAT INSTRUCTIONS:\n{format_instructions}\n\n"
        + (
            f"IMPORTANT — LOW CONFIDENCE WARNING:\n{confidence_warning}\n"
            "Append this warning verbatim at the end of your response.\n\n"
            if confidence_warning else ""
        )
    )

    # ── Step 5: Call LLM (or stub if unavailable) ────────────────────────────
    if _llm_configured():
        answer_text = _call_llm(user_turn, intent=intent, format_override=format_instructions)
    else:
        answer_text = _stub_answer(results, tool_results, intent)

    # ── Step 6: Extract D-007 citations ──────────────────────────────────────
    citations = [r.citation for r in results if r.citation is not None]

    return FinalAnswer(
        answer=answer_text,
        risk_level=risk_level,
        action_type=action_type,
        citations=citations,
        no_evidence_action=None,
        retry_count=retry_count,
        confidence_warning=confidence_warning,
        risk_explain=risk_explain,
        intent_scores=intent_scores,
        intent_top2=intent_top2,
        intent_ambiguous=intent_ambiguous,
    )


# ===========================================================================
# Private helpers
# ===========================================================================

def _format_evidence_block(
    results: list[RetrievalResult],
    tool_results: list[ToolResult],
) -> str:
    """Format retrieved chunks and tool outputs into a structured evidence block."""
    lines: list[str] = []

    for i, r in enumerate(results, 1):
        citation_str = ""
        if r.citation:
            c = r.citation
            citation_str = (
                f"  Source: {c.source_url}\n"
                f"  Section: {c.section_or_title}\n"
                f"  Effective/Updated: {c.effective_date_or_last_updated_or_unknown}\n"
                f"  Accessed: {c.accessed_at}"
            )
        lines.append(
            f"[Evidence {i}]\n"
            f"  Text: {r.text}\n"
            f"{citation_str}"
        )

    for j, t in enumerate(tool_results, 1):
        # Canonical ToolResult fields come from src/schemas.py: output + error.
        # Keep one-cycle backwards compatibility for legacy fields from earlier Role B code.
        output = t.output if hasattr(t, "output") else getattr(t, "output_data", None)
        error = t.error if hasattr(t, "error") else getattr(t, "error_msg", None)

        if error is None:
            lines.append(
                f"[Tool Result {j}: {t.tool_name}]\n"
                f"  Output: {json.dumps(output, indent=2)}"
            )
        else:
            lines.append(
                f"[Tool Result {j}: {t.tool_name} — ERROR]\n"
                f"  Error: {error}"
            )

    return "\n\n".join(lines) if lines else "(no evidence)"


# Maps intent → plain-English action name injected into the system override
_INTENT_ACTION_NAME: dict[str, str] = {
    INTENT_VISUALIZE:  "ACTION 1 — Pathway Overview",
    INTENT_MATCH:      "ACTION 2 — Eligibility Check",
    INTENT_CALCULATE:  "ACTION 3 — CRS Score Calculation",
    INTENT_QA:         "ACTION 4 — Document Checklist / Factual Q&A",
    INTENT_GENERAL:    "ACTION 4 — General Policy Brief",
}


def _call_llm(user_turn: str, intent: str = INTENT_MATCH, format_override: str | None = None) -> str:
    """Call the project-standard LLM client (D-010 settings from .env).

    Injects an action-specific FORMAT OVERRIDE block at the top of the
    system prompt so the LLM's generic output rules are superseded by the
    action-specific structure requested for this turn.

    max_tokens is set to 2048 to give qwen3 reasoning mode enough budget
    to both think and produce a full differentiated response.

    Args:
        format_override: When provided, use this format string instead of the
            default _ACTION_FORMAT lookup (used for QA sub-type selection).
    """
    action_name = _INTENT_ACTION_NAME.get(intent, "ACTION 2 — Eligibility Check")
    format_instructions = format_override if format_override is not None else _ACTION_FORMAT.get(intent, _ACTION_FORMAT[INTENT_MATCH])

    action_override = (
        f"=== ACTIVE ACTION FOR THIS TURN: {action_name} ===\n"
        f"You MUST structure your entire response according to these instructions "
        f"and IGNORE the generic OUTPUT FORMAT RULES below for this turn:\n\n"
        f"{format_instructions}\n\n"
        f"This is the ONLY response format allowed for this turn.\n"
        f"=========================================================\n\n"
    )

    system_content = action_override + get_system_prompt()

    return generate(
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user",   "content": user_turn},
        ],
        temperature=0.1,
        max_tokens=2048,
    )


def _stub_answer(
    results: list[RetrievalResult],
    tool_results: list[ToolResult],
    intent: str,
) -> str:
    """Stub answer builder used when LLM is unavailable (tests / offline mode)."""
    top = results[0]
    citation = top.citation
    section = (top.metadata.get("section_or_title")
               or (citation.section_or_title if citation else "unknown"))
    source  = (top.metadata.get("source_url")
               or (citation.source_url if citation else "unknown"))

    base = (
        f"[{intent.upper()} — STUB ANSWER]\n\n"
        f"Based on the official policy section '{section}', "
        f"the key information is:\n\n{top.text}"
    )

    if tool_results and ((tool_results[0].error if hasattr(tool_results[0], "error") else getattr(tool_results[0], "error_msg", None)) is None):
        output = tool_results[0].output if hasattr(tool_results[0], "output") else getattr(tool_results[0], "output_data", None)
        base += (
            f"\n\nTool result ({tool_results[0].tool_name}): "
            f"{json.dumps(output)}"
        )

    base += (
        f"\n\n---\n"
        f"Source: {source}\n"
        "This is an informational summary. Always verify on the official page."
    )
    return base


# ===========================================================================
# Self-Check
# ===========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  src/agent_module.py — self-check")
    print("=" * 60 + "\n")

    # ── Test 1: detect_intent() ──────────────────────────────────────────────
    assert detect_intent("What is my CRS score?") == INTENT_CALCULATE
    print("[PASS] 1: CRS query → 'calculate'\n")

    assert detect_intent("Am I eligible for OINP Masters Graduate?") == INTENT_MATCH
    print("[PASS] 2: Eligibility query → 'match'\n")

    assert detect_intent("What documents do I need for Express Entry?") == INTENT_QA
    print("[PASS] 3: Document query → 'qa'\n")

    assert detect_intent("What PR pathways exist for me?") == INTENT_VISUALIZE
    print("[PASS] 4: Pathway overview → 'visualize'\n")

    assert detect_intent("What is the minimum IELTS score for FSW?") == INTENT_QA
    print("[PASS] 5: Factual minimum query → 'qa'\n")

    # ── Test 2: route_risk() ─────────────────────────────────────────────────
    empty_p = build_empty_profile()

    # Empty profile → DATA_COLLECTION → L1
    rl1 = route_risk(empty_p, [], "What is the minimum score for FSW?")
    assert rl1 == RiskLevel.L1, f"Expected L1, got {rl1}"
    print("[PASS] 6: Empty profile → L1 (DATA_COLLECTION mode)\n")

    # L3 safety gate
    rl_l3 = route_risk(empty_p, [], "Can you guarantee I will get PR approval?")
    assert rl_l3 == RiskLevel.L3
    print("[PASS] 7: Guarantee request → L3 (safety gate)\n")

    # Full profile + match intent + no evidence → L3 (escalated)
    full_p = build_empty_profile()
    update_profile(full_p, {f: "x" for f in REQUIRED_FIELDS})
    full_p.canadian_work_months = 12
    rl_escalated = route_risk(full_p, [], "Am I eligible for OINP?")
    assert rl_escalated == RiskLevel.L3
    print("[PASS] 8: Full profile + match + no evidence → L3 (escalated)\n")

    # Full profile + match intent + evidence → L2
    fake_results = [
        RetrievalResult(
            chunk_id="c1",
            text="Applicants must have a master's degree from an Ontario university.",
            score=0.95,
            metadata={"section_or_title": "Requirements", "source_url": "https://ontario.ca/oinp"},
            citation=Citation(
                source_url="https://ontario.ca/oinp",
                section_or_title="Requirements",
                effective_date_or_last_updated_or_unknown="2025-01-01",
                accessed_at="2026-04-08T00:00:00Z",
            ),
        )
    ]
    rl_l2 = route_risk(full_p, fake_results, "Am I eligible for OINP?")
    assert rl_l2 == RiskLevel.L2
    print("[PASS] 9: Full profile + match + evidence → L2\n")

    # calculate intent → L1 (even with full profile)
    rl_calc = route_risk(full_p, [], "What is my CRS score?")
    assert rl_calc == RiskLevel.L1
    print("[PASS] 10: CRS query → L1 (calculate intent)\n")

    # ── Test 3: build_answer() ───────────────────────────────────────────────

    # L3 → immediate refusal
    ans_l3 = build_answer(full_p, [], [], RiskLevel.L3,
                          user_text="guarantee my approval")
    assert ans_l3.no_evidence_action == NoEvidenceAction.REFUSE
    assert "RCIC" in ans_l3.answer or "cannot" in ans_l3.answer.lower()
    print("[PASS] 11: build_answer L3 → REFUSE (no LLM call)\n")

    # L1 + no evidence → CITE_GAP
    ans_l1_no = build_answer(full_p, [], [], RiskLevel.L1,
                             user_text="What is the minimum IELTS score?")
    assert ans_l1_no.no_evidence_action == NoEvidenceAction.CITE_GAP
    print("[PASS] 12: build_answer L1 + no evidence → CITE_GAP\n")

    # L2 + no evidence → PARTIAL_ANSWER
    ans_l2_no = build_answer(full_p, [], [], RiskLevel.L2,
                             user_text="Am I eligible for OINP?")
    assert ans_l2_no.no_evidence_action == NoEvidenceAction.PARTIAL_ANSWER
    print("[PASS] 13: build_answer L2 + no evidence → PARTIAL_ANSWER\n")

    # L2 + evidence → stub answer with 1 citation, detect_intent → 'match'
    ans_l2_hit = build_answer(
        full_p, fake_results, [], RiskLevel.L2,
        user_text="Am I eligible for OINP Masters?",
    )
    assert ans_l2_hit.no_evidence_action is None
    assert len(ans_l2_hit.citations) == 1
    assert ans_l2_hit.citations[0].source_url == "https://ontario.ca/oinp"
    assert ans_l2_hit.action_type == ActionType.ACTION_2  # match → ACTION_2
    print("[PASS] 14: build_answer L2 + evidence → answer with citation, ACTION_2\n")

    # L1 + evidence + calculate intent → ACTION_3
    ans_calc = build_answer(
        full_p, fake_results, [], RiskLevel.L1,
        user_text="What is my CRS score?",
    )
    assert ans_calc.action_type == ActionType.ACTION_3
    print("[PASS] 15: build_answer calculate intent → ACTION_3\n")

    print("=" * 60)
    print("  All checks passed. src/agent_module.py is ready.")
    print("=" * 60)
