"""
Shared Pydantic schemas — the integration contract between all modules.

Owner: Yuhan Ren (Role C, Framework Owner)
All modules MUST import from here; do NOT define local schema duplicates.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    """
    D-003: Risk routing levels.
    L1 = general info, no personal advice needed.
    L2 = personalized, low-stakes (no legal/financial consequences).
    L3 = high-stakes (legal, financial, status-affecting).
    """
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class NoEvidenceAction(str, Enum):
    """D-003: What to do when retrieval returns no relevant evidence."""
    CITE_GAP = "cite_gap"          # L1: acknowledge gap, cite where to check
    PARTIAL_ANSWER = "partial_answer"  # L2: answer what is known, flag uncertainty
    REFUSE = "refuse"              # L3: refuse and redirect to official source


# ---------------------------------------------------------------------------
# Citation schema (D-007)
# ---------------------------------------------------------------------------


class Citation(BaseModel):
    source_url: str
    section_or_title: str
    effective_date_or_last_updated_or_unknown: str
    accessed_at: str  # ISO 8601 date string, e.g. "2026-04-07"


# ---------------------------------------------------------------------------
# Intake / user query
# ---------------------------------------------------------------------------


class IntakeProfile(BaseModel):
    """Structured representation of what the user is asking about."""
    query: str
    province: str | None = None
    program: str | None = None   # e.g. "Express Entry", "PNP", "SUV"
    stream: str | None = None
    user_situation: str | None = None  # free-text context the user provides


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


class RetrievalRequest(BaseModel):
    query: str
    province: str | None = None
    program: str | None = None
    stream: str | None = None
    source_type: str | None = None
    effective_date: date | None = None
    top_k_initial: int = Field(default=20, description="D-004: initial retrieval count before rerank")
    top_k_final: int = Field(default=5, description="D-004: count after rerank")


class RetrievalResult(BaseModel):
    chunk_id: str
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    citation: Citation | None = None  # populated when metadata is sufficient


# ---------------------------------------------------------------------------
# Policy / tool calls
# ---------------------------------------------------------------------------


class ToolRequest(BaseModel):
    tool_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool_name: str
    output: Any
    error: str | None = None


# ---------------------------------------------------------------------------
# Final answer
# ---------------------------------------------------------------------------


class FinalAnswer(BaseModel):
    answer: str
    risk_level: RiskLevel
    no_evidence_action: NoEvidenceAction | None = None
    citations: list[Citation] = Field(default_factory=list)
    disclaimer: str | None = None  # Required for L3 answers
    retry_count: int = Field(default=0, description="D-003: max 1 retry allowed")
