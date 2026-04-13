"""
Orchestrator — wires all modules together into a single pipeline call.

Owner: Ehraaz Atif (Role E — Integration) + Yuhan Ren (Framework Owner)
Integration boundary: all inter-module calls go through here.

Pipeline:
  IntakeProfile
    → retrieval_module.retrieve()       (Keqing)
    → policy_tool_module.run_tool()     (Yuhan, optional)
    → agent_module.route_risk()         (Ella)
    → agent_module.build_answer()       (Ella)
    → FinalAnswer
"""

from __future__ import annotations

from src import agent_module, policy_tool_module, retrieval_module
from src.intake import extract_fields, update_profile
from src.schemas import FinalAnswer, IntakeProfile, RetrievalRequest, ToolRequest


def run_pipeline(profile: IntakeProfile) -> FinalAnswer:
    """
    Run the full RAG pipeline for a user query.
    Returns a FinalAnswer with citations.
    """
    # Step 0: Enrich profile from free-text query for downstream routing/tools.
    working_profile = profile.model_copy(deep=True)
    extracted = extract_fields(profile.query)
    if extracted:
        update_profile(working_profile, extracted)

    # Step 1: Detect intent early and short-circuit L3 safety requests.
    intent, intent_scores, intent_top2, intent_ambiguous = agent_module.detect_intent_with_confidence(
        working_profile.query
    )
    if agent_module.is_l3_query(working_profile.query):
        return agent_module.build_answer(
            working_profile,
            results=[],
            tool_results=[],
            risk_level=agent_module.RiskLevel.L3,
            retry_count=0,
            user_text=working_profile.query,
            action_type=None,
            risk_explain={"decision": "L3", "steps": [{"gate": "l3_pattern", "matched": True}]},
            intent_scores=intent_scores,
            intent_top2=intent_top2,
            intent_ambiguous=intent_ambiguous,
        )

    if intent_ambiguous:
        return FinalAnswer(
            answer=agent_module.build_intent_clarification(intent_top2),
            risk_level=agent_module.RiskLevel.L1,
            action_type=agent_module.ActionType.ACTION_4,
            confidence_warning="Intent unclear. Please choose one task so I can be precise.",
            citations=[],
            no_evidence_action=agent_module.NoEvidenceAction.CITE_GAP,
            retry_count=0,
            intent_scores=intent_scores,
            intent_top2=intent_top2,
            intent_ambiguous=True,
            risk_explain={
                "decision": "L1",
                "steps": [
                    {"gate": "intent_ambiguity", "triggered": True, "intent_top2": intent_top2}
                ],
            },
        )

    # Step 2: Retrieve relevant chunks (intent-aware filtering).
    if intent in (agent_module.INTENT_MATCH, agent_module.INTENT_VISUALIZE):
        retrieval_request = RetrievalRequest(
            query=working_profile.query,
            province=working_profile.province,
            program=working_profile.program,
            stream=working_profile.stream,
        )
    else:
        # For general factual/policy queries, avoid over-filtering by sparse profile fields.
        retrieval_request = RetrievalRequest(query=working_profile.query)
    results = retrieval_module.retrieve(retrieval_request)

    # Step 3: Run policy tools when the current intent benefits from them.
    tool_results = []
    if intent == agent_module.INTENT_CALCULATE:
        required = ["age_band", "education_level", "language_score", "canadian_work_months"]
        if sum(1 for field in required if getattr(working_profile, field, None) is not None) >= 3:
            tool_results.append(
                policy_tool_module.run_tool(
                    ToolRequest(
                        tool_name="crs_calculator",
                        parameters=working_profile.model_dump(),
                    )
                )
            )
    elif intent == agent_module.INTENT_VISUALIZE:
        tool_results.append(
            policy_tool_module.run_tool(
                ToolRequest(
                    tool_name="pathway_backbone",
                    parameters=working_profile.model_dump(),
                )
            )
        )

    # Step 4: Route risk level
    risk_level, risk_explain = agent_module.route_risk_with_explain(
        working_profile,
        results,
        user_text=working_profile.query,
    )

    # Step 5: D-003 retry logic — one retry if no evidence on first pass
    answer = agent_module.build_answer(
        working_profile,
        results,
        tool_results,
        risk_level,
        retry_count=0,
        user_text=working_profile.query,
        risk_explain=risk_explain,
        intent_scores=intent_scores,
        intent_top2=intent_top2,
        intent_ambiguous=intent_ambiguous,
    )
    if not results and answer.retry_count == 0:
        results = retrieval_module.retrieve(
            RetrievalRequest(query=working_profile.query)  # broader retry without filters
        )
        risk_level, risk_explain = agent_module.route_risk_with_explain(
            working_profile,
            results,
            user_text=working_profile.query,
        )
        answer = agent_module.build_answer(
            working_profile,
            results,
            tool_results,
            risk_level,
            retry_count=1,
            user_text=working_profile.query,
            risk_explain=risk_explain,
            intent_scores=intent_scores,
            intent_top2=intent_top2,
            intent_ambiguous=intent_ambiguous,
        )

    return answer
