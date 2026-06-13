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

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import logging

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

from src import logging_setup
from src.config import settings

log = logging.getLogger("app")

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")

SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "21600"))  # 6h
MAX_HISTORY_MESSAGES = int(os.environ.get("MAX_HISTORY_MESSAGES", "40"))


# ---------------------------------------------------------------------------
# Observability: per-request id, latency telemetry, structured logging
# ---------------------------------------------------------------------------

@app.before_request
def _start_timer():
    request._start_time = time.time()  # type: ignore[attr-defined]
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    logging_setup.set_request_id(rid)
    request._request_id = rid  # type: ignore[attr-defined]


@app.after_request
def _log_request(response: "Response"):
    try:
        elapsed_ms = (time.time() - getattr(request, "_start_time", time.time())) * 1000
        response.headers["X-Request-ID"] = getattr(request, "_request_id", "-")
        response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.0f}"
        if request.path.startswith("/api/"):
            log.info(
                "%s %s -> %s (%.0fms)",
                request.method, request.path, response.status_code, elapsed_ms,
            )
    except Exception:
        pass
    return response


@app.errorhandler(Exception)
def _handle_uncaught(exc: Exception):
    log.exception("unhandled error on %s %s: %s", request.method, request.path, exc)
    return jsonify({"error": "internal_error", "request_id": getattr(request, "_request_id", "-")}), 500


# Rate limiting (graceful if flask-limiter is unavailable).
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["120 per minute"],
        storage_uri="memory://",
    )
except Exception as _exc:  # pragma: no cover
    limiter = None
    log.info("rate limiting disabled (flask-limiter unavailable): %s", _exc)


def _prewarm_retrieval_index() -> None:
    """Pre-load the ChromaDB vector index on startup so the first user request
    does not incur a 2-5 minute cold-start embedding delay."""
    import threading

    def _load():
        try:
            from src import retrieval_module
            retrieval_module.retrieve(
                __import__("src.schemas", fromlist=["RetrievalRequest"]).RetrievalRequest(
                    query="express entry eligibility"
                )
            )
            print("[prewarm] Retrieval index ready.")
        except Exception as exc:
            print(f"[prewarm] Warning: could not pre-load index: {exc}")

    t = threading.Thread(target=_load, daemon=True)
    t.start()


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
        self._lock = threading.RLock()

    def create(self) -> tuple[str, object, object]:
        """Create a new session. Returns (session_id, machine, session)."""
        from src.intake import IntakeStateMachine

        machine = IntakeStateMachine()
        session = machine.start_session()
        session_id = str(uuid.uuid4())
        with self._lock:
            self._sessions[session_id] = {
                "machine": machine,
                "session": session,
                "original_query": None,
                "current_question": None,
                "conv_history": [],   # list of {"role": "user"|"assistant", "content": str}
                "created_at": time.time(),
                "last_accessed": time.time(),
            }
        return session_id

    def get(self, session_id: str) -> dict | None:
        with self._lock:
            data = self._sessions.get(session_id)
            if data is not None:
                data["last_accessed"] = time.time()
            return data

    def exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._sessions

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def prune_expired(self, ttl_seconds: int = SESSION_TTL_SECONDS) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            stale = [
                sid for sid, payload in self._sessions.items()
                if now - float(payload.get("last_accessed", now)) > ttl_seconds
            ]
            for sid in stale:
                self._sessions.pop(sid, None)
                removed += 1
        return removed


_store = SessionStore()


@dataclass
class ChatTurnContext:
    session_id: str
    data: dict
    session: object
    turn: object
    message: str
    was_ready_before: bool
    extracted_fields: dict
    base_meta: dict
    pipeline_query: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_collecting_message_from_profile(profile) -> str:
    """Build a collecting prompt from the latest profile snapshot.

    UX goals:
    - Never ask for fields that are already filled in the sidebar form.
    - Explicitly tell users the minimum threshold (6/8 required fields)
      before eligibility matching can begin.
    """
    from src.intake import REQUIRED_FIELDS, _FIELD_META

    d = profile.model_dump()
    missing = [f for f in REQUIRED_FIELDS if d.get(f) is None]
    filled_count = len(REQUIRED_FIELDS) - len(missing)

    # Ask up to two next missing fields, matching intake.py behavior.
    prompts: list[str] = []
    for i, field in enumerate(missing[:2], 1):
        prompt = _FIELD_META.get(field, {}).get(
            "prompt",
            f"Please provide your {field.replace('_', ' ')}.",
        )
        prompts.append(f"{i}. {prompt}")

    lines = [
        "I have recorded the profile details you already filled.",
        (
            "To start eligibility assessment, please complete at least "
            "6 of 8 required fields "
            f"(currently {filled_count}/8)."
        ),
    ]
    if prompts:
        lines.append("")
        lines.append("Please add these next:")
        lines.extend(prompts)

    return "\n".join(lines)

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

    optional: list[dict] = []
    for f in OPTIONAL_FIELDS:
        val = d.get(f)
        if val is not None:
            optional.append({
                "field": f,
                "label": f.replace("_", " ").title(),
                "value": val,
            })

    return {"required": required, "optional": optional}


def _contains_new_question(message: str) -> bool:
    msg_lower = message.lower()
    return (
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


def _trim_conv_history(history: list[dict], max_messages: int = MAX_HISTORY_MESSAGES) -> list[dict]:
    if len(history) <= max_messages:
        return history
    return history[-max_messages:]


def _append_conv_history(data: dict, role: str, content: str) -> list[dict]:
    history: list[dict] = data.setdefault("conv_history", [])
    history.append({"role": role, "content": content})
    data["conv_history"] = _trim_conv_history(history)
    return data["conv_history"]


def _build_pipeline_query(data: dict, message: str, was_ready_before: bool) -> str:
    if was_ready_before:
        if _contains_new_question(message):
            data["current_question"] = message
        return data.get("current_question") or data["original_query"] or message
    pipeline_query = data["original_query"] or message
    if pipeline_query:
        data["current_question"] = pipeline_query
    return pipeline_query


def _ensure_turn_ready(turn, data: dict, session, message: str, profile_overrides: dict | None) -> None:
    """Apply profile overrides + intake bypass rules before pipeline call."""
    if profile_overrides:
        from src.schemas import IntakeProfile
        from src.intake import assess_completeness, IntakeMode, ConversationState
        d = session.profile.model_dump()
        d.update(profile_overrides)
        session.profile = IntakeProfile(**d)
        completeness = assess_completeness(session.profile)
        if completeness.mode in (IntakeMode.FULL_MATCHING, IntakeMode.LOW_CONFIDENCE):
            if session.state.value not in ("ready_to_match", "matching_done", "low_confidence_match"):
                session.state = ConversationState.READY_TO_MATCH
            if not turn.ready_for_retrieval:
                turn.ready_for_retrieval = True
                turn.agent_message = ""
        elif completeness.mode == IntakeMode.DATA_COLLECTION and not turn.ready_for_retrieval:
            turn.agent_message = _build_collecting_message_from_profile(session.profile)

    # Bypass profile gate for factual / general / calculate / L3 requests.
    if not turn.ready_for_retrieval:
        from src.agent_module import detect_intent, is_l3_query, INTENT_QA, INTENT_GENERAL, INTENT_CALCULATE
        _orig = data["original_query"] or message
        _intent = detect_intent(_orig)
        if _intent in (INTENT_QA, INTENT_GENERAL, INTENT_CALCULATE) or is_l3_query(_orig):
            turn.ready_for_retrieval = True
            turn.agent_message = ""


def _bootstrap_chat_turn(session_id: str, message: str, profile_overrides: dict | None) -> ChatTurnContext:
    if not _store.exists(session_id):
        raise KeyError("session_not_found")

    data = _store.get(session_id)
    machine = data["machine"]
    session = data["session"]

    if data["original_query"] is None:
        data["original_query"] = message

    was_ready_before = session.state.value in ("ready_to_match", "matching_done", "low_confidence_match")
    profile_before = session.profile.model_dump()
    turn = machine.process_turn(session, message)
    profile_after = session.profile.model_dump()
    extracted_fields = {k: v for k, v in profile_after.items() if v is not None and v != profile_before.get(k)}

    _ensure_turn_ready(turn, data, session, message, profile_overrides or {})
    base_meta = {
        "session_id": session_id,
        "state": session.state.value,
        "profile": _profile_summary(session.profile),
        "ready_for_retrieval": turn.ready_for_retrieval,
        "action_route": turn.action_route.value if turn.action_route else None,
        "extracted_fields": extracted_fields,
    }
    return ChatTurnContext(
        session_id=session_id,
        data=data,
        session=session,
        turn=turn,
        message=message,
        was_ready_before=was_ready_before,
        extracted_fields=extracted_fields,
        base_meta=base_meta,
    )


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
    """Liveness probe — process is up."""
    return jsonify({"status": "ok", "env": settings.env})


@app.route("/api/ready", methods=["GET"])
def ready():
    """Readiness probe — dependencies are usable (retrieval + LLM config)."""
    checks = {"llm_configured": bool(settings.llm.api_key and settings.llm.endpoint)}
    backend = settings.retrieval.backend
    checks["retrieval_backend"] = backend
    try:
        if backend == "pgvector":
            from src import vector_store
            checks["vector_count"] = vector_store.count()
            checks["retrieval_ready"] = checks["vector_count"] > 0
        else:
            checks["retrieval_ready"] = True
    except Exception as exc:
        checks["retrieval_ready"] = False
        checks["retrieval_error"] = str(exc)[:160]
    ok = checks.get("retrieval_ready", False) and checks["llm_configured"]
    return jsonify({"ready": ok, "checks": checks}), (200 if ok else 503)


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

    if not message:
        return jsonify({"error": "Empty message."}), 400

    profile_overrides = {k: v for k, v in (body.get("profile_overrides") or {}).items() if v is not None and v != ""}
    try:
        ctx = _bootstrap_chat_turn(session_id, message, profile_overrides)
    except KeyError:
        return jsonify({"error": "Session not found. Please refresh and start over."}), 404
    except Exception as exc:
        return jsonify({"error": f"Processing error: {exc}"}), 500

    base = {
        "session_id": session_id,
        "state": ctx.session.state.value,
        "profile": _profile_summary(ctx.session.profile),
        "ready_for_retrieval": ctx.turn.ready_for_retrieval,
        "action_route": ctx.turn.action_route.value if ctx.turn.action_route else None,
        "confidence_warning": ctx.turn.confidence_warning or "",
        "extracted_fields": ctx.extracted_fields,
    }

    if not ctx.turn.ready_for_retrieval:
        # ── Intake still collecting ──────────────────────────────────────────
        base["type"] = "collecting"
        base["agent_message"] = ctx.turn.agent_message
        return jsonify(base)

    # ── Ready — run the full pipeline ────────────────────────────────────────
    try:
        from src.orchestrator import run_pipeline
        pipeline_query = _build_pipeline_query(ctx.data, ctx.message, ctx.was_ready_before)
        ctx.pipeline_query = pipeline_query
        ctx.session.profile.query = pipeline_query
        conv_history = _append_conv_history(ctx.data, "user", pipeline_query)

        answer = run_pipeline(ctx.session.profile, conv_history=conv_history)

        # Append assistant answer to history (plain text, no citations)
        clean_answer = _clean_answer_text(answer.answer)
        _append_conv_history(ctx.data, "assistant", clean_answer)

        base["type"] = "answer"
        base["agent_message"] = ctx.turn.agent_message  # acknowledgment / transition msg
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


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    """Streaming variant of /api/chat using Server-Sent Events.

    SSE event types emitted:
      {"type":"status",  "message":"..."}        — progress label
      {"type":"token",   "content":"..."}        — LLM token chunk
      {"type":"done",    "answer":"...",          — full metadata on finish
                         "citations":[...], ...}
      {"type":"error",   "message":"..."}        — on failure
    """
    body = request.get_json(force=True) or {}
    session_id = body.get("session_id", "")
    message = body.get("message", "").strip()

    if not message:
        def _err2():
            yield f"data: {json.dumps({'type':'error','message':'Empty message.'})}\n\n"
        return Response(stream_with_context(_err2()), mimetype="text/event-stream")

    try:
        profile_overrides = {k: v for k, v in (body.get("profile_overrides") or {}).items() if v is not None and v != ""}
        ctx = _bootstrap_chat_turn(session_id, message, profile_overrides)
    except KeyError:
        def _err():
            yield f"data: {json.dumps({'type':'error','message':'Session not found. Please refresh.'})}\n\n"
        return Response(stream_with_context(_err()), mimetype="text/event-stream")
    except Exception as _exc:
        def _setup_err(_m=str(_exc)):
            yield f"data: {json.dumps({'type':'error','message':f'Processing error: {_m}'})}\n\n"
        return Response(stream_with_context(_setup_err()), mimetype="text/event-stream")

    if not ctx.turn.ready_for_retrieval:
        def _collecting():
            yield f"data: {json.dumps({'type':'collecting','agent_message':ctx.turn.agent_message,**ctx.base_meta})}\n\n"
        return Response(stream_with_context(_collecting()), mimetype="text/event-stream")

    pipeline_query = _build_pipeline_query(ctx.data, ctx.message, ctx.was_ready_before)
    ctx.pipeline_query = pipeline_query
    ctx.session.profile.query = pipeline_query
    conv_history = _append_conv_history(ctx.data, "user", pipeline_query)

    def _generate():
        from src import agent_module, policy_tool_module, retrieval_module
        from src.schemas import RetrievalRequest, ToolRequest
        from src.llm_client import generate_stream

        try:
            yield f"data: {json.dumps({'type':'status','message':'Searching policy documents…'})}\n\n"

            # Step 1: intent + L3 check
            intent, intent_scores, intent_top2, intent_ambiguous = \
                agent_module.detect_intent_with_confidence(pipeline_query)

            if agent_module.is_l3_query(pipeline_query):
                refusal = agent_module.get_l3_refusal()
                _append_conv_history(ctx.data, "assistant", refusal)
                yield f"data: {json.dumps({'type':'done','answer':refusal,'citations':[],'risk_level':'L3','action_type':None,'confidence_warning':'','retry_count':0,**ctx.base_meta})}\n\n"
                return

            # Step 2: retrieval
            if intent in (agent_module.INTENT_MATCH, agent_module.INTENT_VISUALIZE):
                rr = RetrievalRequest(
                    query=pipeline_query,
                    province=ctx.session.profile.province,
                    program=ctx.session.profile.program,
                    stream=ctx.session.profile.stream,
                )
            else:
                rr = RetrievalRequest(query=pipeline_query)
            results = retrieval_module.retrieve(rr)

            # Step 3: policy tools
            tool_results = []
            if intent == agent_module.INTENT_CALCULATE:
                required = ["age_band","education_level","language_score","canadian_work_months"]
                if sum(1 for f in required if getattr(ctx.session.profile, f, None) is not None) >= 3:
                    tool_results.append(policy_tool_module.run_tool(
                        ToolRequest(tool_name="crs_calculator", parameters=ctx.session.profile.model_dump())
                    ))
            elif intent == agent_module.INTENT_VISUALIZE:
                tool_results.append(policy_tool_module.run_tool(
                    ToolRequest(tool_name="pathway_backbone", parameters=ctx.session.profile.model_dump())
                ))

            # Retry if no results
            if not results:
                results = retrieval_module.retrieve(RetrievalRequest(query=pipeline_query))

            # Step 4: risk routing
            risk_level, risk_explain = agent_module.route_risk_with_explain(
                ctx.session.profile, results, user_text=pipeline_query
            )

            # Step 5: prepare stream context
            early_answer, messages, citations, confidence_warning, action_type = \
                agent_module.prepare_stream_context(
                    ctx.session.profile, results, tool_results, risk_level,
                    user_text=pipeline_query,
                    risk_explain=risk_explain,
                    intent_scores=intent_scores,
                    intent_top2=intent_top2,
                    intent_ambiguous=intent_ambiguous,
                    conv_history=conv_history,
                )

            # Early return for L3 / no-evidence
            if early_answer is not None:
                clean = _clean_answer_text(early_answer.answer)
                _append_conv_history(ctx.data, "assistant", clean)
                yield f"data: {json.dumps({'type':'done','answer':clean,'citations':[],'risk_level':risk_level.value,'action_type':action_type.value if action_type else None,'confidence_warning':confidence_warning,'retry_count':0,**ctx.base_meta})}\n\n"
                return

            # Step 6: stream LLM tokens
            yield f"data: {json.dumps({'type':'status','message':'Generating answer…'})}\n\n"
            full_text = []
            for token in generate_stream(messages):
                full_text.append(token)
                yield f"data: {json.dumps({'type':'token','content':token})}\n\n"

            answer_text = _clean_answer_text("".join(full_text))
            _append_conv_history(ctx.data, "assistant", answer_text)

            citations_data = [c.model_dump() for c in citations]
            yield f"data: {json.dumps({'type':'done','answer':answer_text,'citations':citations_data,'risk_level':risk_level.value,'action_type':action_type.value if action_type else None,'confidence_warning':confidence_warning,'retry_count':0,**ctx.base_meta})}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'type':'error','message':str(exc)})}\n\n"

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
# Status endpoint (used by frontend banner)
# ---------------------------------------------------------------------------

@app.route("/api/status", methods=["GET"])
def status():
    """Check whether the ChromaDB retrieval index is built and populated."""
    _store.prune_expired()
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    host, port = settings.web_host, settings.web_port
    log.info("Starting Canada PR Navigator on http://%s:%s (env=%s)", host, port, settings.env)
    log.info("Web UI: /   Health: /api/health   Ready: /api/ready")
    _prewarm_retrieval_index()
    # Development server only. In production run via gunicorn (see Dockerfile):
    #   gunicorn -w 2 -k gthread -b 0.0.0.0:5050 src.app:app
    app.run(host=host, port=port, debug=False, use_reloader=False)
