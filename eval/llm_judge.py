"""
LLM-as-a-judge — RAGAS-style answer evaluation with calibration.

Scores three dimensions per (query, answer, contexts) triple, each 0-100:
  - context_relevance : are the retrieved contexts relevant to the query?
  - faithfulness      : is every claim in the answer grounded in the contexts?
  - answer_relevance  : does the answer actually address the user's question?

The MVP only stubbed this ("replace with LLM judge in later sprint"). This is
the real implementation (Decision D-011).

KNOWN LIMITATIONS (documented deliberately; mitigations applied where noted):
  - Model bias / position bias: a single judge may favor verbose or same-family
    outputs. Mitigation: rubric is explicit and per-dimension; we score one
    answer at a time (no pairwise position effect).
  - Cost & latency: one LLM call per sample. Mitigation: judge runs as an
    offline batch job, not in the request path; --limit caps sample count.
  - Calibration: judge scores are only trustworthy if they track human
    judgement. `calibrate()` correlates judge faithfulness against the existing
    manual hallucination labels and reports agreement.
  - Prompt sensitivity: clear rubrics + a strict JSON schema + few-shot anchors
    materially improve reliability; weaker models still struggle on nuance, so
    the judge model should be at least as capable as the generation model.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from statistics import mean

from src.llm_client import generate

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_JUDGE_SYSTEM = (
    "You are a meticulous evaluation judge for a Canadian immigration RAG "
    "assistant. You score answers ONLY against the provided contexts and the "
    "user question. You never use outside knowledge to fill gaps. You are "
    "strict: unsupported specifics lower faithfulness even if they sound "
    "plausible. Respond with ONLY a JSON object, no prose."
)

_RUBRIC = """Score each dimension from 0 to 100.

context_relevance:
  100 = contexts directly contain the information needed to answer
  50  = contexts are topically related but miss the specific answer
  0   = contexts are unrelated to the question

faithfulness (grounding):
  100 = every factual claim in the answer is supported by the contexts
  75  = minor unsupported generalization, no false core claim
  50  = at least one claim not supported by contexts
  0   = answer contradicts contexts or fabricates policy

answer_relevance:
  100 = fully and directly answers the user's question
  50  = partially answers or is padded with irrelevant content
  0   = does not address the question (or empty)

Return EXACTLY:
{"context_relevance": <int>, "faithfulness": <int>, "answer_relevance": <int>, "reasoning": "<one sentence>"}"""


def _build_prompt(query: str, answer: str, contexts: list[str]) -> list[dict]:
    ctx_block = "\n\n".join(f"[Context {i}]\n{c}" for i, c in enumerate(contexts, 1)) or "(no contexts)"
    user = (
        f"{_RUBRIC}\n\n"
        f"USER QUESTION:\n{query}\n\n"
        f"RETRIEVED CONTEXTS:\n{ctx_block}\n\n"
        f"ASSISTANT ANSWER:\n{answer or '(empty)'}\n\n"
        f"Return the JSON now."
    )
    return [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {"role": "user", "content": user},
    ]


def _parse_scores(raw: str) -> dict:
    """Extract the JSON object from the judge output, robust to wrapping text."""
    if not raw:
        return {}
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    out = {}
    for key in ("context_relevance", "faithfulness", "answer_relevance"):
        try:
            out[key] = max(0, min(100, int(round(float(data.get(key, 0))))))
        except (TypeError, ValueError):
            out[key] = 0
    out["reasoning"] = str(data.get("reasoning", ""))[:300]
    return out


def judge(query: str, answer: str, contexts: list[str], model: str | None = None) -> dict:
    """Score a single (query, answer, contexts) triple. Returns dimension scores."""
    raw = generate(
        _build_prompt(query, answer, contexts),
        model=model,
        max_tokens=300,
        temperature=0.0,
    )
    scores = _parse_scores(raw)
    if not scores:
        scores = {"context_relevance": 0, "faithfulness": 0, "answer_relevance": 0,
                  "reasoning": "judge parse failure", "parse_error": True}
    return scores


# ---------------------------------------------------------------------------
# Batch judging over eval samples (runs the live pipeline per sample)
# ---------------------------------------------------------------------------

def run_batch(samples_path: Path, limit: int | None, model: str | None) -> dict:
    from src.schemas import IntakeProfile
    from src.orchestrator import run_pipeline

    rows = []
    with open(samples_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                rows.append(json.loads(line))
    rows = [r for r in rows if not r.get("expect_refuse")]
    if limit:
        rows = rows[:limit]

    results = []
    for s in rows:
        ans = run_pipeline(IntakeProfile(query=s["query"]))
        contexts = []
        # Reconstruct contexts from citations is lossy; re-retrieve for fidelity.
        from src import retrieval_module
        from src.schemas import RetrievalRequest
        retr = retrieval_module.retrieve(RetrievalRequest(query=s["query"], top_k_final=5))
        contexts = [r.text for r in retr]
        scores = judge(s["query"], ans.answer, contexts, model=model)
        scores["id"] = s.get("id")
        results.append(scores)

    def _avg(key):
        vals = [r[key] for r in results if key in r]
        return round(mean(vals), 2) if vals else 0.0

    return {
        "num_samples": len(results),
        "judge_model": model or "default",
        "mean_context_relevance": _avg("context_relevance"),
        "mean_faithfulness": _avg("faithfulness"),
        "mean_answer_relevance": _avg("answer_relevance"),
        "details": results,
    }


# ---------------------------------------------------------------------------
# Calibration against manual human labels
# ---------------------------------------------------------------------------

def calibrate(judge_report: dict, manual_path: Path) -> dict:
    """Correlate judge faithfulness with manual hallucination scores.

    Reports Pearson correlation and band-agreement so the team can decide how
    much to trust the automated judge before relying on it at scale.
    """
    if not manual_path.exists():
        return {"error": f"manual labels not found: {manual_path}"}
    manual = json.loads(manual_path.read_text(encoding="utf-8"))
    manual_by_id = {}
    for item in manual.get("samples", manual.get("details", [])):
        sid = item.get("id") or item.get("sample_id")
        score = item.get("score", item.get("manual_score"))
        if sid is not None and score is not None:
            manual_by_id[sid] = float(score)

    pairs = []
    for r in judge_report.get("details", []):
        sid = r.get("id")
        if sid in manual_by_id and "faithfulness" in r:
            pairs.append((float(r["faithfulness"]), manual_by_id[sid]))

    if len(pairs) < 3:
        return {"paired": len(pairs), "note": "insufficient overlap to calibrate"}

    judge_scores = [p[0] for p in pairs]
    human_scores = [p[1] for p in pairs]
    corr = _pearson(judge_scores, human_scores)
    agree = mean(1.0 if abs(j - h) <= 25 else 0.0 for j, h in pairs)
    return {
        "paired": len(pairs),
        "pearson_r": round(corr, 3),
        "band_agreement_within_25pts": round(agree, 3),
        "mean_judge": round(mean(judge_scores), 1),
        "mean_human": round(mean(human_scores), 1),
    }


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-as-judge (RAGAS-style) + calibration.")
    parser.add_argument("--samples", type=Path, default=PROJECT_ROOT / "eval" / "samples.jsonl")
    parser.add_argument("--limit", type=int, default=10, help="cap samples (cost control)")
    parser.add_argument("--model", type=str, default=None, help="override judge model")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "eval" / "judge_report.json")
    parser.add_argument("--manual", type=Path, default=PROJECT_ROOT / "eval" / "manual_hallucination_report.json")
    args = parser.parse_args()

    report = run_batch(args.samples, args.limit, args.model)
    report["calibration"] = calibrate(report, args.manual)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "details"}, indent=2, ensure_ascii=False))
    print(f"\nWrote {args.out}")
