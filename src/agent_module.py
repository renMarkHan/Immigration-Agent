"""
Agent module stub.

Owner: Ella Lu (Role A — Agent/Prompting)
Handles: prompt construction, LLM call, response parsing,
         risk routing (D-003), no-evidence fallback.

DO NOT change the function signatures without updating orchestrator.py.
"""

from __future__ import annotations

from src.schemas import (
    FinalAnswer,
    IntakeProfile,
    NoEvidenceAction,
    RetrievalResult,
    RiskLevel,
    ToolResult,
)


def route_risk(profile: IntakeProfile, results: list[RetrievalResult]) -> RiskLevel:
    """
    D-003: Classify query risk level.

    L1 — general info, no personal advice needed
    L2 — personalized, low-stakes
    L3 — high-stakes (legal / financial / status-affecting)

    TODO (Ella): implement classification logic.
    """
    return RiskLevel.L1


def build_answer(
    profile: IntakeProfile,
    results: list[RetrievalResult],
    tool_results: list[ToolResult],
    risk_level: RiskLevel,
    retry_count: int = 0,
) -> FinalAnswer:
    """
    Construct the LLM prompt, call generate(), parse and return FinalAnswer.

    D-003 no-evidence fallback:
      - No results + L1 → NoEvidenceAction.CITE_GAP
      - No results + L2 → NoEvidenceAction.PARTIAL_ANSWER
      - No results + L3 → NoEvidenceAction.REFUSE (do NOT answer)
    Max 1 retry allowed (retry_count <= 1).

    TODO (Ella): implement prompt builder and response parser.
    """
    if not results:
        action_map = {
            RiskLevel.L1: NoEvidenceAction.CITE_GAP,
            RiskLevel.L2: NoEvidenceAction.PARTIAL_ANSWER,
            RiskLevel.L3: NoEvidenceAction.REFUSE,
        }
        return FinalAnswer(
            answer="[Stub] No evidence retrieved.",
            risk_level=risk_level,
            no_evidence_action=action_map[risk_level],
            retry_count=retry_count,
        )

    top = results[0]
    section = top.metadata.get("section_or_title", "unknown")
    source = top.metadata.get("source_url", "unknown")

    answer_text = (
        f"Based on the retrieved official source section '{section}', "
        f"the key requirements are summarized as: {top.text}"
    )

    citations = [r.citation for r in results if r.citation is not None]
    return FinalAnswer(
        answer=answer_text,
        risk_level=risk_level,
        citations=citations,
        retry_count=retry_count,
        disclaimer=(
            "This is an informational summary. Verify details on the official page: "
            f"{source}"
        ),
    )
