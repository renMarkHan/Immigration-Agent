"""
Demonstration script for the Ontario Masters requirement retrieval flow.

Run:
  python -m src.demo_ontario_flow

Goal:
  Show teammates the expected process shape:
    ingest source -> retrieve requirement section -> answer with citation.
"""

from __future__ import annotations

import json

from src.ingestion_module import ingest
from src.orchestrator import run_pipeline
from src.schemas import IntakeProfile

SOURCE_URL = "https://www.ontario.ca/page/oinp-masters-graduate-stream"
DEMO_QUERY = "what is the requirement for ontario master graduate stream?"


def run_demo() -> None:
    print("=== Step 1: Ingest demo source ===")
    count = ingest(SOURCE_URL)
    print(f"Chunks written: {count}")

    print("\n=== Step 2: Ask demo query ===")
    profile = IntakeProfile(
        query=DEMO_QUERY,
        province="Ontario",
        program="OINP",
        stream="Masters Graduate Stream",
    )
    answer = run_pipeline(profile)

    print("\n=== Step 3: Output ===")
    print(json.dumps(answer.model_dump(), indent=2, ensure_ascii=True, default=str))


if __name__ == "__main__":
    run_demo()
