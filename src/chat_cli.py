"""
Minimal conversational CLI for the agent.

Run:
  python -m src.chat_cli

Purpose:
  Provide a real interactive loop for asking questions through orchestrator.
  This is intentionally simple and extensible for future UX/API layers.
"""

from __future__ import annotations

import json

from dotenv import load_dotenv

from src.orchestrator import run_pipeline
from src.schemas import IntakeProfile

load_dotenv()


def _print_help() -> None:
    print("Commands:")
    print("  /help                 Show help")
    print("  /show                 Show current profile context")
    print("  /set province <value> Set province context")
    print("  /set program <value>  Set program context")
    print("  /set stream <value>   Set stream context")
    print("  /clear                Clear context fields")
    print("  /exit                 Quit")


def _render_answer(answer_obj) -> None:
    print("\n=== Agent Response ===")
    print(f"risk_level: {answer_obj.risk_level}")
    if answer_obj.no_evidence_action:
        print(f"no_evidence_action: {answer_obj.no_evidence_action}")
    if answer_obj.disclaimer:
        print(f"disclaimer: {answer_obj.disclaimer}")
    print("answer:")
    print(answer_obj.answer)

    print("\ncitations:")
    if not answer_obj.citations:
        print("  (none)")
    else:
        for idx, c in enumerate(answer_obj.citations, start=1):
            print(f"  [{idx}] {c.source_url}")
            print(f"      section/title: {c.section_or_title}")
            print(
                "      effective_or_updated: "
                f"{c.effective_date_or_last_updated_or_unknown}"
            )
            print(f"      accessed_at: {c.accessed_at}")

    print("\nraw_json:")
    print(json.dumps(answer_obj.model_dump(), ensure_ascii=True, indent=2, default=str))
    print()


def _parse_set(command: str, state: dict[str, str | None]) -> None:
    parts = command.split(maxsplit=2)
    if len(parts) < 3:
        print("Usage: /set <province|program|stream> <value>")
        return

    key = parts[1].strip().lower()
    value = parts[2].strip()
    if key not in {"province", "program", "stream"}:
        print("Only province/program/stream can be set.")
        return

    state[key] = value
    print(f"Set {key} = {value}")


def run_chat_cli() -> None:
    print("Canada Immigration & PR Navigator - Minimal Chat CLI")
    print("Type /help for commands, /exit to quit.\n")

    state: dict[str, str | None] = {
        "province": None,
        "program": None,
        "stream": None,
    }

    while True:
        user_input = input("you> ").strip()
        if not user_input:
            continue

        if user_input == "/exit":
            print("Bye.")
            break
        if user_input == "/help":
            _print_help()
            continue
        if user_input == "/show":
            print(json.dumps(state, ensure_ascii=True, indent=2))
            continue
        if user_input == "/clear":
            state = {"province": None, "program": None, "stream": None}
            print("Context cleared.")
            continue
        if user_input.startswith("/set "):
            _parse_set(user_input, state)
            continue

        profile = IntakeProfile(
            query=user_input,
            province=state["province"],
            program=state["program"],
            stream=state["stream"],
        )
        answer_obj = run_pipeline(profile)
        _render_answer(answer_obj)


if __name__ == "__main__":
    run_chat_cli()
