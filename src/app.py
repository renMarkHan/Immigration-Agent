"""
src/app.py — Web API + UX server for Canada Immigration & PR Navigator

Owner: Ehraaz Atif (Role E — Integration & UX)
Wraps IntakeStateMachine + run_pipeline in an HTTP API for the web frontend.

Endpoints:
    POST /api/session          — Create a new intake session
    POST /api/chat             — Process one conversation turn
    GET  /api/session/<id>     — Get current session state (profile + state)
    GET  /api/health           — Health check

Run:
    python -m src.app
    (or: flask --app src.app run --port 5050)
"""

from __future__ import annotations

import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")


# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Answer text cleaning
# ---------------------------------------------------------------------------

def _clean_answer_text(text: str) -> str:
    """Strip LLM citation blocks and boilerplate from the answer body.

    The LLM emits citations in two ways:
      (a) single-line:  { "source_url": "...", ... }
      (b) multi-line:   {
                          "source_url": "...",
                          ...
                        }
    Both are already in answer.citations[] and must be removed from prose.
    Also strips [LOW CONFIDENCE] lines, the trailing disclaimer, and the
    "Citations:" header the model sometimes inserts.
    """
    import re as _re

    # Pass 1: remove any { ... } block containing "source_url" (handles both
    # single-line and multi-line citation JSON emitted by the LLM).
    text = _re.sub(r'\{[^{}]*?"source_url"[^{}]*?\}', '', text, flags=_re.DOTALL)

    # Pass 2: line-by-line cleanup of leftover boilerplate
    out, skip_blank = [], False
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("[LOW CONFIDENCE]") or s.startswith("[DATA COLLECTION MODE]"):
            skip_blank = True; continue
        if _re.match(r"^citations\s*:?\s*$", s, _re.IGNORECASE):
            skip_blank = True; continue
        if s.startswith("This information is for general guidance only"):
            skip_blank = True; continue
        if s == "---":
            skip_blank = True; continue
        if s == "" and skip_blank:
            skip_blank = False; continue
        skip_blank = False
        out.append(line)

    return "\n".join(out).strip()

class SessionStore:
    """Simple in-memory session store. Suitable for demo/MVP."""

    def __init__(self):
        self._sessions: dict[str, dict] = {}

    def create(self) -> tuple[str, object, object]:
        """Create a new session. Returns (session_id, machine, session)."""
        from src.intake import IntakeStateMachine

        machine = IntakeStateMachine()
        session = machine.start_session()
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = {
            "machine": machine,
            "session": session,
            "original_query": None,
            "current_question": None,
            "conv_history": [],   # list of {"role": "user"|"assistant", "content": str}
        }
        return session_id

    def get(self, session_id: str) -> dict | None:
        return self._sessions.get(session_id)

    def exists(self, session_id: str) -> bool:
        return session_id in self._sessions


_store = SessionStore()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _profile_summary(profile) -> dict:
    """Return a display-friendly dict of collected profile fields."""
    from src.intake import REQUIRED_FIELDS, OPTIONAL_FIELDS, _FIELD_META

    d = profile.model_dump()
    required = []
    for f in REQUIRED_FIELDS:
        required.append({
            "field": f,
            "label": _FIELD_META[f]["label"],
            "value": d.get(f),
            "filled": d.get(f) is not None,
        })
    optional = []
    for f in OPTIONAL_FIELDS:
        val = d.get(f)
        if val is not None:
            optional.append({"field": f, "label": f.replace("_", " ").title(), "value": val})

    return {"required": required, "optional": optional}


# ---------------------------------------------------------------------------
# Routes — Static files
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(str(WEB_DIR), "index.html")


# ---------------------------------------------------------------------------
# Routes — API
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/session", methods=["POST"])
def create_session():
    """Create a new intake session and return its ID + greeting message."""
    session_id = _store.create()
    data = _store.get(session_id)
    machine = data["machine"]
    session = data["session"]

    # Kick off with a greeting turn (empty message triggers GREETING state)
    turn = machine.process_turn(session, "")

    return jsonify({
        "session_id": session_id,
        "state": session.state.value,
        "agent_message": turn.agent_message,
        "profile": _profile_summary(session.profile),
        "ready_for_retrieval": False,
    })


@app.route("/api/chat", methods=["POST"])
def chat():
    """Process one conversation turn."""
    body = request.get_json(force=True) or {}
    session_id = body.get("session_id", "")
    message = body.get("message", "").strip()

    if not _store.exists(session_id):
        return jsonify({"error": "Session not found. Please refresh and start over."}), 404

    if not message:
        return jsonify({"error": "Empty message."}), 400

    data = _store.get(session_id)
    machine = data["machine"]
    session = data["session"]

    # ── Run intake turn ──────────────────────────────────────────────────────
    # Save the very first user message as the original question.
    # Intake answers ("No job offer", "I am 27") are not questions —
    # routing detect_intent() on them gives the wrong action type.
    if data["original_query"] is None:
        data["original_query"] = message

    # Snapshot state BEFORE process_turn to detect the ready transition.
    # This must happen before form overrides so that form-driven state changes
    # don't affect the first-message routing logic.
    was_ready_before = session.state.value in (
        "ready_to_match", "matching_done", "low_confidence_match"
    )

    # Snapshot profile before conversation extraction (for P2: extracted_fields diff)
    profile_before_intake = session.profile.model_dump()

    turn = machine.process_turn(session, message)

    # ── Compute conversation-extracted fields (for frontend form sync) ────────
    profile_after_intake = session.profile.model_dump()
    extracted_fields = {
        k: v for k, v in profile_after_intake.items()
        if v is not None and v != profile_before_intake.get(k)
    }

    # ── Apply profile overrides from the frontend form ───────────────────────
    # Applied AFTER process_turn so form-set values always win over conversation
    # extraction. Blank form fields (not sent by frontend) leave conversation
    # values untouched.
    profile_overrides = {k: v for k, v in (body.get("profile_overrides") or {}).items()
                         if v is not None and v != ""}
    if profile_overrides:
        from src.schemas import IntakeProfile
        d = session.profile.model_dump()
        d.update(profile_overrides)
        session.profile = IntakeProfile(**d)

        # If required fields are now filled, skip intake collection entirely
        from src.intake import assess_completeness, IntakeMode, ConversationState
        completeness = assess_completeness(session.profile)
        if completeness.mode in (IntakeMode.FULL_MATCHING, IntakeMode.LOW_CONFIDENCE):
            if session.state.value not in ("ready_to_match", "matching_done", "low_confidence_match"):
                session.state = ConversationState.READY_TO_MATCH
            # Propagate readiness to the current turn so the intake question is
            # not shown when the sidebar form already has the required fields.
            if not turn.ready_for_retrieval:
                turn.ready_for_retrieval = True
                turn.agent_message = ""

    # Bypass profile-collection gate for factual / general / L3 queries.
    # These don't need personal profile fields — answer immediately without
    # asking for age, education, etc.
    if not turn.ready_for_retrieval:
        from src.agent_module import (
            detect_intent_with_confidence,
            is_l3_query,
            INTENT_QA,
            INTENT_GENERAL,
            INTENT_CALCULATE,
        )
        _orig = data["original_query"] or message
        _intent, _, _, _ = detect_intent_with_confidence(_orig)
        if _intent in (INTENT_QA, INTENT_GENERAL, INTENT_CALCULATE) or is_l3_query(_orig):
            turn.ready_for_retrieval = True
            turn.agent_message = ""  # suppress the profile-collection prompt

    base = {
        "session_id": session_id,
        "state": session.state.value,
        "profile": _profile_summary(session.profile),
        "ready_for_retrieval": turn.ready_for_retrieval,
        "action_route": turn.action_route.value if turn.action_route else None,
        "confidence_warning": turn.confidence_warning or "",
        "extracted_fields": extracted_fields,
    }

    if not turn.ready_for_retrieval:
        # ── Intake still collecting ──────────────────────────────────────────
        base["type"] = "collecting"
        base["agent_message"] = turn.agent_message
        return jsonify(base)

    # ── Ready — run the full pipeline ────────────────────────────────────────
    try:
        from src.orchestrator import run_pipeline
        # Determine the query to pass to the pipeline.
        if was_ready_before:
            msg_lower = message.lower()
            is_new_question = (
                '?' in message
                or any(msg_lower.startswith(w) for w in [
                    'what', 'how', 'which', 'why', 'when', 'where', 'who',
                    'am i', 'can i', 'do i', 'will i', 'would i', 'is there',
                    'are there', 'tell me', 'show me', 'explain',
                ])
                or any(kw in msg_lower for kw in [
                    'eligible', 'qualify', 'pathway', 'document', 'calculate',
                    'crs', 'score', 'option', 'program', 'stream', 'apply',
                ])
            )
            if is_new_question:
                data["current_question"] = message
            pipeline_query = data.get("current_question") or data["original_query"] or message
        else:
            pipeline_query = data["original_query"] or message
            if pipeline_query:
                data["current_question"] = pipeline_query
        session.profile.query = pipeline_query

        # Append this user turn to conversation history before calling pipeline
        conv_history: list[dict] = data.setdefault("conv_history", [])
        conv_history.append({"role": "user", "content": pipeline_query})

        answer = run_pipeline(session.profile, conv_history=conv_history)

        # Append assistant answer to history (plain text, no citations)
        clean_answer = _clean_answer_text(answer.answer)
        conv_history.append({"role": "assistant", "content": clean_answer})

        base["type"] = "answer"
        base["agent_message"] = turn.agent_message  # acknowledgment / transition msg
        base["answer"] = clean_answer
        base["risk_level"] = answer.risk_level.value
        base["action_type"] = answer.action_type.value if answer.action_type else None
        base["citations"] = [c.model_dump() for c in answer.citations]
        base["no_evidence_action"] = (
            answer.no_evidence_action.value if answer.no_evidence_action else None
        )
        base["confidence_warning"] = answer.confidence_warning or ""
        base["disclaimer"] = answer.disclaimer or ""
        base["retry_count"] = answer.retry_count

    except Exception as exc:  # noqa: BLE001 — surface errors to UI for demo
        base["type"] = "error"
        base["agent_message"] = (
            f"An error occurred while generating your answer: {exc}\n\n"
            "Please check that your .env file has valid LLM_ENDPOINT, LLM_API_KEY, "
            "and LLM_MODEL values, and that the retrieval index has been built."
        )

    return jsonify(base)


@app.route("/api/session/<session_id>", methods=["GET"])
def get_session(session_id: str):
    """Return current session state (profile + conversation state)."""
    if not _store.exists(session_id):
        return jsonify({"error": "Session not found."}), 404

    data = _store.get(session_id)
    session = data["session"]

    return jsonify({
        "session_id": session_id,
        "state": session.state.value,
        "turn_count": session.turn_count,
        "profile": _profile_summary(session.profile),
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Starting Canada PR Navigator web server on http://localhost:5050")
    print(f"Web UI:  http://localhost:5050/")
    print(f"API:     http://localhost:5050/api/health")
    app.run(host="0.0.0.0", port=5050, debug=True)


@app.route("/api/status", methods=["GET"])
def status():
    """Check whether the ChromaDB retrieval index is built and populated."""
    from pathlib import Path as _Path
    chroma_dir  = _Path(__file__).resolve().parent.parent / "chroma_db"
    chunks_file = _Path(__file__).resolve().parent.parent / "data" / "processed" / "chunks.jsonl"
    index_exists = chroma_dir.exists() and any(chroma_dir.iterdir()) if chroma_dir.exists() else False
    chunks_exist = chunks_file.exists()
    doc_count = 0
    if index_exists:
        try:
            import chromadb as _chromadb
            _c = _chromadb.PersistentClient(path=str(chroma_dir))
            doc_count = _c.get_or_create_collection("policy_chunks").count()
        except Exception:
            doc_count = -1
    return jsonify({
        "index_ready":  index_exists and doc_count > 0,
        "index_exists": index_exists,
        "chunks_file":  chunks_exist,
        "doc_count":    doc_count,
        "message": (
            f"Retrieval index loaded — {doc_count} chunks indexed."
            if doc_count > 0
            else "Retrieval index not built yet. Run: python -m src.ingestion_module"
        ),
    })
