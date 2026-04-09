import sys
import os


# Add the project root to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), "Immigration-Agent-main"))

from src.intake import IntakeStateMachine, ConversationState
from src.agent_module import route_risk, build_answer
from src.schemas import RetrievalResult, Citation

def main():
    print("=== Role B End-to-End Test ===")
    
    # 1. Test Intake
    machine = IntakeStateMachine()
    session = machine.start_session()
    
    print(f"\n[User]: Hi!")
    result = machine.process_turn(session, "Hi!")
    print(f"[Agent]: {result.agent_message}")
    
    print(f"\n[User]: I am 27, I have a Master's degree from University of Toronto, Canada. I live in Ontario.")
    result = machine.process_turn(session, "I am 27, I have a Master's degree from University of Toronto, Canada. I live in Ontario.")
    print(f"[Agent]: {result.agent_message}")
    
    print(f"\n[User]: I have no job offer, graduated in 2024-06, and have 12 months of Canadian work experience. Am I eligible for OINP Masters?")
    result = machine.process_turn(session, "I have no job offer, graduated in 2024-06, and have 12 months of Canadian work experience. Am I eligible for OINP Masters?")
    print(f"[Agent]: {result.agent_message}")
    
    # Check if ready for retrieval
    if result.ready_for_retrieval:
        print(f"\n--- Intake Complete ---")
        print(f"Action Route: {result.action_route}")
        
        # 2. Mock Retrieval
        print("\n--- Mocking Retrieval ---")
        mock_results = [
            RetrievalResult(
                chunk_id="oinp_001",
                text="To be eligible for the OINP Masters Graduate stream, you must have completed a master's degree from an eligible university in Ontario, and apply within two years of completing the requirements necessary to obtain the degree.",
                score=0.9,
                metadata={"section_or_title": "Masters Graduate stream requirements", "source_url": "https://www.ontario.ca/page/oinp-masters-graduate-stream"},
                citation=Citation(
                    source_url="https://www.ontario.ca/page/oinp-masters-graduate-stream",
                    section_or_title="Masters Graduate stream requirements",
                    effective_date_or_last_updated_or_unknown="2024-01-01",
                    accessed_at="2026-04-09T10:00:00Z"
                )
            )
        ]
        
        # 3. Test Risk Routing
        print("\n--- Routing Risk ---")
        user_query = "Am I eligible for OINP Masters?"
        risk_level = route_risk(session.profile, mock_results, user_query)
        print(f"Risk Level detected: {risk_level}")
        
        # 4. Test Answer Generation
        print("\n--- Building Answer ---")
        final_answer = build_answer(
            profile=session.profile,
            results=mock_results,
            tool_results=[],
            risk_level=risk_level,
            user_text=user_query,
            action_type=result.action_route
        )
        print(f"\nFinal Answer Output:\n{final_answer.answer}")
        print(f"\nAction Type: {final_answer.action_type}")
        print(f"Citations: {final_answer.citations}")

if __name__ == '__main__':
    main()
