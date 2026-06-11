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


def run_pipeline(profile: IntakeProfile, conv_history: list[dict] | None = None) -> FinalAnswer:
    """
    Run the full RAG pipeline for a user query.
    Returns a FinalAnswer with citations.

    conv_history: list of {"role": "user"|"assistant", "content": str} from
    previous turns in this session. Injected into the LLM prompt so the model
    can refer back to earlier exchanges (same as Claude/ChatGPT behaviour).
    """
    # Step 0: Enrich profile from free-text query for downstream routing/tools.
    # In web chat flow, intake already extracted and merged fields earlier in
    # the request lifecycle. Re-running extraction here duplicates an extra LLM
    # call and can noticeably increase latency for Action 3/4.
    # Keep extraction for non-chat paths (no conv_history) for compatibility.
    working_profile = profile.model_copy(deep=True)
    if conv_history is None:
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
            conv_history=conv_history,
        )

    # When intent is ambiguous, don't refuse — proceed with the top-ranked intent
    # and surface a soft warning in the response. Hard refusals block the user when
    # they have sent profile-info follow-ups ("I'm 27 years old") that shouldn't
    # have reached the pipeline in the first place (fixed in app.py).
    ambiguity_warning = ""
    if intent_ambiguous:
        ambiguity_warning = (
            f"Your request was a little ambiguous — "
            f"I interpreted it as a {agent_module.build_intent_clarification(intent_top2).split('Do you want')[0].strip()} "
            f"and answered accordingly. If this isn't what you meant, please rephrase."
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
        conv_history=conv_history,
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
            conv_history=conv_history,
        )

    # Attach ambiguity note as a soft warning (does not replace the answer)
    if ambiguity_warning and not answer.confidence_warning:
        answer = answer.model_copy(update={"confidence_warning": ambiguity_warning})

    return answer
