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
from src.schemas import FinalAnswer, IntakeProfile, RetrievalRequest, ToolRequest


def run_pipeline(profile: IntakeProfile) -> FinalAnswer:
    """
    Run the full RAG pipeline for a user query.
    Returns a FinalAnswer with citations.
    """
    # Step 1: Retrieve relevant chunks
    retrieval_request = RetrievalRequest(
        query=profile.query,
        province=profile.province,
        program=profile.program,
        stream=profile.stream,
    )
    results = retrieval_module.retrieve(retrieval_request)

    # Step 2: Run policy tools if applicable (currently stub, no-op)
    tool_results = []
    # TODO (Ehraaz / Yuhan): detect tool intent from profile and call run_tool()

    # Step 3: Route risk level
    risk_level = agent_module.route_risk(profile, results, user_text=profile.query)

    # Step 4: D-003 retry logic — one retry if no evidence on first pass
    answer = agent_module.build_answer(
        profile,
        results,
        tool_results,
        risk_level,
        retry_count=0,
        user_text=profile.query,
    )
    if not results and answer.retry_count == 0:
        results = retrieval_module.retrieve(
            RetrievalRequest(query=profile.query)  # broader retry without filters
        )
        answer = agent_module.build_answer(
            profile,
            results,
            tool_results,
            risk_level,
            retry_count=1,
            user_text=profile.query,
        )

    return answer
