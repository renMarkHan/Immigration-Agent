"""
src/intake.py — Multi-Turn Intake, Field Collection & Scene Routing
Canada Immigration & PR Navigator Agent

Owner:   Keqing Wang (Role B — Agent/Prompt Engineer)
Version: v2.0
Date:    2026-04-08


─────────────────────────────────────────────────────────────────────────────
RESPONSIBILITY OF THIS FILE (intake.py)
─────────────────────────────────────────────────────────────────────────────
  1. Collect the 8 minimum required fields from the user (D-002)
  2. Multi-turn dialog state machine (GREETING → COLLECTING → READY)
  3. Clarification / follow-up question logic when fields are missing
  4. Scene routing: decide which Action (1/2/3/4) to take based on user query

  This file does NOT:
  - Call the LLM to generate final answers  (→ agent_module.py)
  - Determine L1/L2/L3 risk level           (→ agent_module.py)
  - Build prompts or call retrieval          (→ agent_module.py / retrieval_module.py)

─────────────────────────────────────────────────────────────────────────────
PUBLIC API
─────────────────────────────────────────────────────────────────────────────
  Enums
    IntakeMode        — DATA_COLLECTION | LOW_CONFIDENCE | FULL_MATCHING
    ConversationState — GREETING | COLLECTING | LOW_CONFIDENCE_MATCH |
                        READY_TO_MATCH | MATCHING_DONE
    ActionRoute       — ACTION_1 | ACTION_2 | ACTION_3 | ACTION_4

  Dataclasses
    IntakeCompleteness — D-002 completeness result
    IntakeSession     — per-session conversation state
    IntakeTurnResult  — output of one dialog turn

  Functions
    build_empty_profile()   — factory
    update_profile()        — merge extracted fields into profile
    assess_completeness()   — D-002 mode evaluation
    profile_to_context()    — format profile for LLM context injection
    route_scene()           — classify user query → Action 1/2/3/4
    IntakeStateMachine      — multi-turn dialog controller

Frozen design constraints:
  D-002  Minimum Required Intake Fields + missing-field rules
  D-001  Refusal Policy: Option A tiered (answer / clarify / refuse)
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.schemas import IntakeProfile


# ===========================================================================
# SECTION 1 — Enums
# ===========================================================================

class IntakeMode(str, Enum):
    """D-002 operating mode derived from profile completeness."""
    DATA_COLLECTION = "data_collection"
    """More than 2 required fields missing — collect data only, no matching."""
    LOW_CONFIDENCE  = "low_confidence"
    """1–2 required fields missing — pre-screening with warning allowed."""
    FULL_MATCHING   = "full_matching"
    """All 8 required fields present — full eligibility matching enabled."""


class ConversationState(str, Enum):
    """States of the multi-turn intake dialog."""
    GREETING             = "greeting"
    COLLECTING           = "collecting"
    LOW_CONFIDENCE_MATCH = "low_confidence_match"
    READY_TO_MATCH       = "ready_to_match"
    MATCHING_DONE        = "matching_done"


class ActionRoute(str, Enum):
    """The four product Actions (scene routing output).

    ACTION_1 — Pathway overview:    'What PR pathways exist for me?'
    ACTION_2 — Eligibility check:   'Am I eligible for stream X?'
    ACTION_3 — CRS calculation:     'What is my CRS score?'
    ACTION_4 — Document checklist:  'What documents do I need?'
    """
    ACTION_1 = "action_1"
    ACTION_2 = "action_2"
    ACTION_3 = "action_3"
    ACTION_4 = "action_4"


# ===========================================================================
# SECTION 2 — IntakeProfile Schema (D-002)
# ===========================================================================
# Canonical IntakeProfile is defined in src/schemas.py.


# Ordered list — collection priority order
REQUIRED_FIELDS: list[str] = [
    "age_band",
    "education_level",
    "language_score",
    "current_province",
    "target_province",
    "job_offer_status",
    "graduation_date",
    "canadian_work_months",
]

OPTIONAL_FIELDS: list[str] = [
    "noc_code",
    "foreign_work_months",
    "canadian_degree",
    "second_language_score",
    "spouse_education",
    "spouse_language_score",
    "spouse_canadian_work_months",
]

# Human-readable labels and clarification prompts for each required field
_FIELD_META: dict[str, dict] = {
    "age_band": {
        "label": "Age",
        "prompt": "How old are you? (e.g. 27)",
    },
    "education_level": {
        "label": "Highest Education Level",
        "prompt": (
            "What is your highest completed education level, and was it "
            "obtained in Canada or abroad? "
            "(e.g. Master's degree obtained in Canada)"
        ),
    },
    "language_score": {
        "label": "Language Test Score",
        "prompt": (
            "What are your scores on your most recent official language test "
            "(IELTS General, CELPIP General, TEF Canada, or TCF Canada)? "
            "Please provide scores for all four skills: "
            "Reading, Writing, Listening, Speaking."
        ),
    },
    "current_province": {
        "label": "Current Province",
        "prompt": "Which Canadian province or territory are you currently living in?",
    },
    "target_province": {
        "label": "Target Province for Settlement",
        "prompt": (
            "Which Canadian province or territory do you plan to settle in "
            "after receiving PR? (Can be the same as your current province.)"
        ),
    },
    "job_offer_status": {
        "label": "Job Offer Status",
        "prompt": (
            "Do you currently have a valid job offer from a Canadian employer? "
            "Please answer yes, no, or I'm not sure."
        ),
    },
    "graduation_date": {
        "label": "Graduation Date",
        "prompt": (
            "When did you (or will you) graduate from your most recent degree "
            "program? Please provide the month and year. "
            "(Important for OINP stream eligibility windows.)"
        ),
    },
    "canadian_work_months": {
        "label": "Canadian Skilled Work Experience",
        "prompt": (
            "How many months of skilled work experience (TEER 0, 1, 2, or 3) "
            "do you have in Canada? Count only paid, full-time or equivalent "
            "part-time work. Enter 0 if none."
        ),
    },
}


# ===========================================================================
# SECTION 3 — Profile helpers
# ===========================================================================

def build_empty_profile() -> IntakeProfile:
    """Return a fresh IntakeProfile with all fields set to None."""
    return IntakeProfile(query="")


def update_profile(profile: IntakeProfile, extracted: dict) -> IntakeProfile:
    """Merge extracted field values into the profile (in-place).

    Unknown keys are silently ignored. None values do NOT overwrite existing data.
    """
    known = set(REQUIRED_FIELDS + OPTIONAL_FIELDS)
    for key, value in extracted.items():
        if key in known and value is not None:
            setattr(profile, key, value)
    return profile


@dataclass
class IntakeCompleteness:
    """D-002 completeness assessment result."""
    mode: IntakeMode
    missing_required: list[str]
    missing_optional: list[str]
    confidence_warning: str  # empty string when mode == FULL_MATCHING


def assess_completeness(profile) -> IntakeCompleteness:
    """Evaluate the profile and return the D-002 operating mode."""
    d = profile.model_dump()
    missing_req = [f for f in REQUIRED_FIELDS if d.get(f) is None]
    missing_opt = [f for f in OPTIONAL_FIELDS if d.get(f) is None]
    n = len(missing_req)

    if n > 2:
        mode = IntakeMode.DATA_COLLECTION
        warning = (
            f"[DATA COLLECTION MODE] {n} required fields are still missing "
            f"({', '.join(missing_req)}). "
            "I can collect your information but cannot perform eligibility "
            "matching until more details are provided."
        )
    elif n >= 1:
        mode = IntakeMode.LOW_CONFIDENCE
        warning = (
            f"[LOW CONFIDENCE] {n} required field(s) are missing "
            f"({', '.join(missing_req)}). "
            "The following assessment is approximate. Please provide the "
            "missing information for a reliable result."
        )
    else:
        mode = IntakeMode.FULL_MATCHING
        warning = ""

    return IntakeCompleteness(
        mode=mode,
        missing_required=missing_req,
        missing_optional=missing_opt,
        confidence_warning=warning,
    )


def profile_to_context(profile) -> str:
    """Format the profile as a structured string for LLM context injection."""
    d = profile.model_dump()
    lines = ["USER PROFILE:"]
    for f in REQUIRED_FIELDS:
        val = d.get(f)
        label = _FIELD_META[f]["label"]
        lines.append(f"  {label}: {val if val is not None else '[not provided]'}")
    for f in OPTIONAL_FIELDS:
        val = d.get(f)
        if val is not None:
            lines.append(f"  {f.replace('_', ' ').title()}: {val}")
    return "\n".join(lines)


# ===========================================================================
# SECTION 4 — Scene Routing: Action 1/2/3/4
# ===========================================================================

# ── Keyword patterns for rule-based scene routing ───────────────────────────

# ACTION_1: pathway overview / "what pathways exist for me?"
_ACTION_1_KEYWORDS: list[str] = [
    "pathway", "pathways", "options", "routes", "ways to get pr",
    "how to get pr", "what programs", "which programs", "overview",
    "what streams", "which streams", "what can i apply",
]

# ACTION_2: eligibility check / "am I eligible?"
_ACTION_2_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\beligib",
        r"\bqualif",
        r"\bcan i (apply|get|receive)\b",
        r"\bdo i (meet|qualify|have enough)\b",
        r"\bam i (eligible|able to)\b",
        r"\bwould i (qualify|be eligible)\b",
        r"\bmy (eligibility|application|profile)\b",
        r"\brequirement",
        r"\bcriteria\b",
    ]
]

# ACTION_3: CRS score calculation
_ACTION_3_KEYWORDS: list[str] = [
    "crs", "crs score", "comprehensive ranking", "points",
    "score", "calculate", "calculator", "how many points",
    "what is my score", "my score",
]

# ACTION_4: document checklist
_ACTION_4_KEYWORDS: list[str] = [
    "document", "documents", "checklist", "what do i need",
    "what papers", "what files", "what to submit", "required documents",
    "supporting documents", "proof of", "evidence of",
]


def route_scene(user_text: str) -> ActionRoute:
    """Classify user query into one of the four product Actions.

    Priority order: ACTION_3 > ACTION_4 > ACTION_2 > ACTION_1
    (more specific intents take precedence over general ones)

    Args:
        user_text: Raw user message.

    Returns:
        ActionRoute enum value.

    Examples:
        >>> route_scene("What is my CRS score?")
        ActionRoute.ACTION_3

        >>> route_scene("Am I eligible for OINP Masters?")
        ActionRoute.ACTION_2

        >>> route_scene("What documents do I need?")
        ActionRoute.ACTION_4

        >>> route_scene("What PR pathways exist for me?")
        ActionRoute.ACTION_1
    """
    text_lower = user_text.lower()

    # ACTION_3: CRS / score calculation (most specific)
    for kw in _ACTION_3_KEYWORDS:
        if kw in text_lower:
            return ActionRoute.ACTION_3

    # ACTION_4: document checklist
    for kw in _ACTION_4_KEYWORDS:
        if kw in text_lower:
            return ActionRoute.ACTION_4

    # ACTION_2: eligibility check (pattern-based)
    for pattern in _ACTION_2_PATTERNS:
        if pattern.search(user_text):
            return ActionRoute.ACTION_2

    # ACTION_1: pathway overview (default for general queries)
    for kw in _ACTION_1_KEYWORDS:
        if kw in text_lower:
            return ActionRoute.ACTION_1

    # Default: eligibility check (most common user intent)
    return ActionRoute.ACTION_2


# ===========================================================================
# SECTION 5 — Multi-Turn Dialog State Machine
# ===========================================================================

@dataclass
class IntakeSession:
    """Per-session conversation state."""
    session_id: str
    profile: IntakeProfile
    state: ConversationState
    turn_count: int = 0
    last_action_route: Optional[ActionRoute] = None


@dataclass
class IntakeTurnResult:
    """Output of one conversation turn from the state machine."""
    session_id: str
    state: ConversationState
    agent_message: str
    """The message to send to the user (greeting, question, or acknowledgment)."""
    ready_for_retrieval: bool
    """True when the profile is complete enough to proceed to retrieval."""
    action_route: Optional[ActionRoute]
    """Which Action to execute (set when ready_for_retrieval=True)."""
    profile_context: str
    """Formatted profile string for LLM context injection."""
    confidence_warning: str
    """Non-empty when operating in LOW_CONFIDENCE mode."""


class IntakeStateMachine:
    """Multi-turn dialog controller.

    Manages the conversation flow from greeting through field collection
    to readiness for retrieval and answer generation.

    Usage:
        machine = IntakeStateMachine()
        session = machine.start_session()

        # Each user turn:
        result = machine.process_turn(session, user_message)
        print(result.agent_message)   # send to user

        # When ready:
        if result.ready_for_retrieval:
            # pass result.profile_context + result.action_route to agent_module
            pass
    """

    # Max clarification questions per turn
    _MAX_QUESTIONS_PER_TURN = 2
    _MAX_QUESTIONS_LOW_CONFIDENCE = 1

    def start_session(self) -> IntakeSession:
        """Create a new intake session."""
        return IntakeSession(
            session_id=str(uuid.uuid4()),
            profile=build_empty_profile(),
            state=ConversationState.GREETING,
        )

    def process_turn(
        self,
        session: IntakeSession,
        user_message: str,
    ) -> IntakeTurnResult:
        """Process one user message and advance the dialog state.

        Args:
            session:      Current IntakeSession (mutated in-place).
            user_message: Raw user message text.

        Returns:
            IntakeTurnResult with the agent's response and session state.
        """
        session.turn_count += 1

        # Extract any field values from the user message
        extracted = _extract_fields(user_message)
        if extracted:
            update_profile(session.profile, extracted)

        # Determine scene route from user message
        action_route = route_scene(user_message)
        session.last_action_route = action_route

        # Assess completeness
        completeness = assess_completeness(session.profile)

        # ── State transitions ────────────────────────────────────────────────
        if session.state == ConversationState.GREETING:
            session.state = ConversationState.COLLECTING
            return IntakeTurnResult(
                session_id=session.session_id,
                state=session.state,
                agent_message=self._greeting_message(completeness),
                ready_for_retrieval=False,
                action_route=None,
                profile_context=profile_to_context(session.profile),
                confidence_warning="",
            )

        if completeness.mode == IntakeMode.DATA_COLLECTION:
            # More than 2 fields missing — keep collecting
            session.state = ConversationState.COLLECTING
            questions = self._build_questions(
                completeness.missing_required,
                max_q=self._MAX_QUESTIONS_PER_TURN,
            )
            return IntakeTurnResult(
                session_id=session.session_id,
                state=session.state,
                agent_message=(
                    "Thank you for that information. To help you accurately, "
                    "I still need a few more details:\n\n" + questions
                ),
                ready_for_retrieval=False,
                action_route=None,
                profile_context=profile_to_context(session.profile),
                confidence_warning=completeness.confidence_warning,
            )

        if completeness.mode == IntakeMode.LOW_CONFIDENCE:
            # 1–2 fields missing — proceed with warning, ask one more question
            session.state = ConversationState.LOW_CONFIDENCE_MATCH
            question = self._build_questions(
                completeness.missing_required,
                max_q=self._MAX_QUESTIONS_LOW_CONFIDENCE,
            )
            return IntakeTurnResult(
                session_id=session.session_id,
                state=session.state,
                agent_message=(
                    "I have enough information to give you a preliminary assessment, "
                    "but one detail would improve accuracy:\n\n" + question
                    + "\n\nI will proceed with what I have in the meantime."
                ),
                ready_for_retrieval=True,
                action_route=action_route,
                profile_context=profile_to_context(session.profile),
                confidence_warning=completeness.confidence_warning,
            )

        # FULL_MATCHING — all 8 fields present
        session.state = ConversationState.READY_TO_MATCH
        return IntakeTurnResult(
            session_id=session.session_id,
            state=session.state,
            agent_message=(
                "Thank you — I have all the information I need. "
                "Let me look up the relevant policy for you now."
            ),
            ready_for_retrieval=True,
            action_route=action_route,
            profile_context=profile_to_context(session.profile),
            confidence_warning="",
        )

    # ── Private helpers ──────────────────────────────────────────────────────

    def _greeting_message(self, completeness: IntakeCompleteness) -> str:
        """Build the initial greeting + first question(s)."""
        questions = self._build_questions(
            completeness.missing_required,
            max_q=self._MAX_QUESTIONS_PER_TURN,
        )
        return (
            "Hello! I'm your Canada Immigration & PR Navigator. "
            "I can help you explore PR pathways, check your eligibility, "
            "estimate your CRS score, and build a document checklist.\n\n"
            "To get started, I need a few details about your background:\n\n"
            + questions
        )

    def _build_questions(
        self,
        missing_fields: list[str],
        max_q: int = 2,
    ) -> str:
        """Build a numbered list of clarification questions for missing fields."""
        questions = []
        for i, f in enumerate(missing_fields[:max_q], 1):
            meta = _FIELD_META.get(f, {})
            prompt = meta.get("prompt", f"Please provide your {f.replace('_', ' ')}.")
            questions.append(f"{i}. {prompt}")
        return "\n".join(questions)


# ===========================================================================
# SECTION 6 — Field Extractor (rule-based stub)
# ===========================================================================

def extract_fields(user_text: str) -> dict:
    """Public wrapper for rule-based field extraction from free-form text."""
    return _extract_fields(user_text)

def _extract_fields(user_text: str) -> dict:
    """Extract field values from free-form user text.

    This is a rule-based stub for MVP. Replace with LLM structured output
    before the Demo to handle natural language variations reliably.

    Returns a dict of {field_name: value} for any fields detected.
    """
    extracted: dict = {}
    text = user_text.strip()

    # age_band
    age_match = re.search(r"\b(1[89]|[2-5]\d)\b", text)
    if age_match:
        age = int(age_match.group())
        if age < 18:
            pass
        elif age <= 24:
            extracted["age_band"] = "18-24"
        elif age <= 29:
            extracted["age_band"] = "25-29"
        elif age <= 34:
            extracted["age_band"] = "30-34"
        elif age <= 39:
            extracted["age_band"] = "35-39"
        elif age <= 44:
            extracted["age_band"] = "40-44"
        else:
            extracted["age_band"] = "45+"

    # education_level
    edu_patterns = [
        (r"\b(phd|ph\.d|doctorate|doctoral)\b", "Doctorate"),
        (r"\b(master|msc|mba|m\.eng|m\.a\.|master'?s)\b", "Master's"),
        (r"\b(bachelor|bsc|b\.a\.|b\.eng|bachelor'?s|undergraduate)\b", "Bachelor's"),
        (r"\b(diploma|college diploma)\b", "Diploma"),
        (r"\b(high school|secondary school|grade 12)\b", "High School"),
    ]
    for pattern, label in edu_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            # Check if obtained in Canada
            if re.search(r"\bcanada\b|\bcanadian\b|\bontario\b|\bbc\b|\balberta\b", text, re.IGNORECASE):
                extracted["education_level"] = f"{label}, Canada"
            else:
                extracted["education_level"] = label
            break

    # language_score (IELTS / CELPIP / TEF / TCF)
    lang_match = re.search(
        r"\b(ielts|celpip|tef|tcf)\b.{0,60}?([0-9]\.[05]|[0-9])\b",
        text, re.IGNORECASE
    )
    if lang_match:
        extracted["language_score"] = text[:120]  # store raw text for now

    # current_province / target_province
    province_map = {
        "ontario": "Ontario", "on": "Ontario",
        "british columbia": "British Columbia", "bc": "British Columbia",
        "alberta": "Alberta", "ab": "Alberta",
        "quebec": "Quebec", "qc": "Quebec",
        "manitoba": "Manitoba", "mb": "Manitoba",
        "saskatchewan": "Saskatchewan", "sk": "Saskatchewan",
        "nova scotia": "Nova Scotia", "ns": "Nova Scotia",
        "new brunswick": "New Brunswick", "nb": "New Brunswick",
        "pei": "Prince Edward Island", "prince edward island": "Prince Edward Island",
        "newfoundland": "Newfoundland and Labrador", "nl": "Newfoundland and Labrador",
    }
    text_lower = text.lower()
    for key, province in province_map.items():
        if re.search(r"\b" + re.escape(key) + r"\b", text_lower):
            if "current_province" not in extracted:
                extracted["current_province"] = province
            if "target_province" not in extracted:
                extracted["target_province"] = province
            break

    # job_offer_status
    if re.search(r"\b(yes|i have|i do have|i got).{0,20}(job offer|offer)\b", text, re.IGNORECASE):
        extracted["job_offer_status"] = "yes"
    elif re.search(r"\b(no|i don'?t|i do not|no job offer)\b", text, re.IGNORECASE):
        extracted["job_offer_status"] = "no"
    elif re.search(r"\b(not sure|unknown|unsure|maybe)\b", text, re.IGNORECASE):
        extracted["job_offer_status"] = "unknown"

    # graduation_date
    grad_match = re.search(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+20[0-9]{2}\b"
        r"|20[0-9]{2}[-/](0[1-9]|1[0-2])",
        text, re.IGNORECASE
    )
    if grad_match:
        extracted["graduation_date"] = grad_match.group()

    # canadian_work_months
    work_match = re.search(
        r"(\d+)\s*(month|months|yr|year|years).{0,30}(work|experience|job|employ)",
        text, re.IGNORECASE
    )
    if work_match:
        amount = int(work_match.group(1))
        unit = work_match.group(2).lower()
        if "year" in unit:
            amount *= 12
        extracted["canadian_work_months"] = amount
    elif re.search(r"\bno (canadian |canada )?work\b|\b0 month\b|\bnever worked\b", text, re.IGNORECASE):
        extracted["canadian_work_months"] = 0

    return extracted


# ===========================================================================
# Self-Check
# ===========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  src/intake.py — self-check")
    print("=" * 60 + "\n")

    # ── A: Profile completeness ──────────────────────────────────────────────
    p0 = build_empty_profile()
    c0 = assess_completeness(p0)
    assert c0.mode == IntakeMode.DATA_COLLECTION
    assert len(c0.missing_required) == 8
    print(f"[PASS] A1: Empty profile → DATA_COLLECTION, 8 missing\n")

    p1 = build_empty_profile()
    update_profile(p1, {f: "x" for f in REQUIRED_FIELDS[:6]})
    p1.canadian_work_months = 12
    c1 = assess_completeness(p1)
    assert c1.mode == IntakeMode.LOW_CONFIDENCE
    assert "graduation_date" in c1.missing_required
    print(f"[PASS] A2: 7/8 required → LOW_CONFIDENCE\n")

    p2 = build_empty_profile()
    update_profile(p2, {f: "x" for f in REQUIRED_FIELDS})
    p2.canadian_work_months = 12
    c2 = assess_completeness(p2)
    assert c2.mode == IntakeMode.FULL_MATCHING
    assert c2.confidence_warning == ""
    print(f"[PASS] A3: 8/8 required → FULL_MATCHING\n")

    # ── B: Scene routing ─────────────────────────────────────────────────────
    assert route_scene("What is my CRS score?") == ActionRoute.ACTION_3
    print("[PASS] B1: CRS query → ACTION_3\n")

    assert route_scene("Am I eligible for OINP Masters Graduate stream?") == ActionRoute.ACTION_2
    print("[PASS] B2: Eligibility query → ACTION_2\n")

    assert route_scene("What documents do I need for Express Entry?") == ActionRoute.ACTION_4
    print("[PASS] B3: Document query → ACTION_4\n")

    assert route_scene("What PR pathways exist for me?") == ActionRoute.ACTION_1
    print("[PASS] B4: Pathway overview → ACTION_1\n")

    assert route_scene("What options do I have for immigration?") == ActionRoute.ACTION_1
    print("[PASS] B5: General options → ACTION_1\n")

    # ── C: Field extraction ──────────────────────────────────────────────────
    e1 = _extract_fields("I am 27 years old")
    assert e1.get("age_band") == "25-29"
    print("[PASS] C1: Age extraction → 25-29\n")

    e2 = _extract_fields("I have a Master's degree from University of Toronto, Canada")
    assert "Master" in e2.get("education_level", "")
    print("[PASS] C2: Education extraction → Master's, Canada\n")

    e3 = _extract_fields("I live in Ontario")
    assert e3.get("current_province") == "Ontario"
    print("[PASS] C3: Province extraction → Ontario\n")

    e4 = _extract_fields("I graduated in June 2024")
    assert e4.get("graduation_date") is not None
    print("[PASS] C4: Graduation date extraction\n")

    e5 = _extract_fields("I have no Canadian work experience")
    assert e5.get("canadian_work_months") == 0
    print("[PASS] C5: Zero work months extraction\n")

    # ── D: State machine ─────────────────────────────────────────────────────
    machine = IntakeStateMachine()
    session = machine.start_session()
    assert session.state == ConversationState.GREETING
    print("[PASS] D1: New session → GREETING\n")

    r1 = machine.process_turn(session, "I am 27, I have a Master's from University of Toronto Canada")
    assert session.state == ConversationState.COLLECTING
    assert not r1.ready_for_retrieval
    print(f"[PASS] D2: Turn 1 → COLLECTING, ready=False\n")

    # Fill most fields
    update_profile(session.profile, {
        "language_score": "IELTS R7 W6.5 L8 S7",
        "current_province": "Ontario",
        "target_province": "Ontario",
        "job_offer_status": "no",
        "graduation_date": "2024-06",
        "canadian_work_months": 12,
    })
    r2 = machine.process_turn(session, "Am I eligible for OINP Masters?")
    assert r2.ready_for_retrieval
    assert r2.action_route == ActionRoute.ACTION_2
    print(f"[PASS] D3: All fields filled → ready_for_retrieval=True, ACTION_2\n")

    print("=" * 60)
    print("  All checks passed. src/intake.py is ready.")
    print("=" * 60)
