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

    # Step 1: Retrieve relevant chunks
    retrieval_request = RetrievalRequest(
        query=working_profile.query,
        province=working_profile.province,
        program=working_profile.program,
        stream=working_profile.stream,
    )
    results = retrieval_module.retrieve(retrieval_request)

    # Step 2: Run policy tools when the current intent benefits from them.
    tool_results = []
    intent = agent_module.detect_intent(working_profile.query)
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

    # Step 3: Route risk level
    risk_level = agent_module.route_risk(working_profile, results, user_text=working_profile.query)

    # Step 4: D-003 retry logic — one retry if no evidence on first pass
    answer = agent_module.build_answer(
        working_profile,
        results,
        tool_results,
        risk_level,
        retry_count=0,
        user_text=working_profile.query,
    )
    if not results and answer.retry_count == 0:
        results = retrieval_module.retrieve(
            RetrievalRequest(query=working_profile.query)  # broader retry without filters
        )
        answer = agent_module.build_answer(
            working_profile,
            results,
            tool_results,
            risk_level,
            retry_count=1,
            user_text=working_profile.query,
        )

    return answer
