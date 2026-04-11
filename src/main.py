"""
Entry point — `python -m src.main`

Runs two checks:
  1. LLM connectivity test (real endpoint call)
  2. Mock pipeline run (stub modules, no ChromaDB needed)
"""

from __future__ import annotations

import json

from dotenv import load_dotenv

load_dotenv()


def _test_llm_connectivity() -> None:
    print("=== LLM Connectivity Test ===")
    from src.llm_client import generate

    reply = generate(
        messages=[{"role": "user", "content": "Reply with the single word: connected"}],
        max_tokens=64,
    )
    print(f"LLM response: {reply!r}")
    print("PASS\n")


def _test_mock_pipeline() -> None:
    print("=== Mock Pipeline Run ===")
    from src.orchestrator import run_pipeline
    from src.schemas import IntakeProfile

    profile = IntakeProfile(
        query=(
            "I am 27 years old with a Master's degree in Canada, IELTS 8 7 7 7, "
            "and 12 months of Canadian skilled work experience. What is my CRS score?"
        ),
        program="Express Entry",
    )
    answer = run_pipeline(profile)
    print(json.dumps(answer.model_dump(), indent=2, default=str))
    print("PASS\n")


if __name__ == "__main__":
    _test_llm_connectivity()
    _test_mock_pipeline()
    print("All checks passed. Scaffold is ready.")
