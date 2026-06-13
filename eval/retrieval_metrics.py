"""
Retrieval-quality evaluation — Recall@k, Hit@k, MRR@k.

The MVP eval measured only answer-level signals (factual accuracy, citation
quality, refusal). It never measured the retriever itself, so there was no
evidence that hybrid retrieval beat plain BM25. This module closes that gap
(Decision D-011).

Relevance labels, in priority order per sample:
  1. gold_chunk_ids   — explicit chunk-level gold (best; add when available)
  2. gold_source_urls — doc-level gold: a retrieved chunk is relevant if its
                        source_url matches a gold URL
  3. expected_answer_contains — automated proxy: a chunk is relevant if it
                        contains an expected key phrase (no manual labeling)

Metrics (computed at k = 1, 3, 5, 10):
  - Hit@k     : fraction of queries with >=1 relevant chunk in the top-k
  - MRR@k     : mean reciprocal rank of the first relevant chunk
  - Recall@k  : with phrase proxy -> fraction of expected phrases covered by
                top-k; with gold ids/urls -> |relevant∩topk| / |relevant|

Run:
    python -m eval.retrieval_metrics
    python -m eval.retrieval_metrics --k 1 3 5 10 --samples eval/samples.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean

from src.schemas import RetrievalRequest
from src import retrieval_module

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLES = PROJECT_ROOT / "eval" / "samples.jsonl"
DEFAULT_OUT = PROJECT_ROOT / "eval" / "retrieval_report.json"


def _load_samples(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _relevance_flags(sample: dict, results: list) -> tuple[list[bool], float]:
    """Return (per-rank relevance flags, recall_value) for one query.

    recall_value semantics depend on the available label type.
    """
    gold_ids = set(sample.get("gold_chunk_ids", []) or [])
    gold_urls = set(sample.get("gold_source_urls", []) or [])
    phrases = [p.lower() for p in sample.get("expected_answer_contains", []) or []]

    flags: list[bool] = []
    if gold_ids:
        for r in results:
            flags.append(r.chunk_id in gold_ids)
        retrieved_rel = {r.chunk_id for r, f in zip(results, flags) if f}
        recall = len(retrieved_rel) / len(gold_ids) if gold_ids else 0.0
        return flags, recall

    if gold_urls:
        for r in results:
            url = (r.metadata or {}).get("source_url", "")
            flags.append(any(g in url or url in g for g in gold_urls))
        hit_urls = {
            (r.metadata or {}).get("source_url", "")
            for r, f in zip(results, flags) if f
        }
        recall = len(hit_urls & gold_urls) / len(gold_urls) if gold_urls else 0.0
        return flags, recall

    # Phrase proxy
    covered: set[str] = set()
    for r in results:
        text = r.text.lower()
        rel = False
        for p in phrases:
            if p in text:
                covered.add(p)
                rel = True
        flags.append(rel)
    recall = len(covered) / len(phrases) if phrases else 0.0
    return flags, recall


def _mrr(flags: list[bool]) -> float:
    for i, f in enumerate(flags, 1):
        if f:
            return 1.0 / i
    return 0.0


def evaluate(samples_path: Path, ks: list[int], out_path: Path) -> dict:
    samples = _load_samples(samples_path)
    # Skip refusal samples: there is no "relevant document" to retrieve.
    samples = [s for s in samples if not s.get("expect_refuse")]
    max_k = max(ks)

    per_k: dict[int, dict[str, list[float]]] = {k: {"hit": [], "mrr": [], "recall": []} for k in ks}
    details = []

    for s in samples:
        req = RetrievalRequest(
            query=s["query"],
            top_k_initial=max(20, max_k * 4),
            top_k_final=max_k,
        )
        results = retrieval_module.retrieve(req)
        flags_full, _ = _relevance_flags(s, results)
        row = {"id": s.get("id"), "query": s["query"], "label_type": _label_type(s)}
        for k in ks:
            flags_k = flags_full[:k]
            _, recall_k = _relevance_flags(s, results[:k])
            hit = 1.0 if any(flags_k) else 0.0
            mrr = _mrr(flags_k)
            per_k[k]["hit"].append(hit)
            per_k[k]["mrr"].append(mrr)
            per_k[k]["recall"].append(recall_k)
            row[f"hit@{k}"] = hit
            row[f"mrr@{k}"] = round(mrr, 4)
            row[f"recall@{k}"] = round(recall_k, 4)
        details.append(row)

    aggregates = {
        f"k={k}": {
            "hit_rate": round(mean(per_k[k]["hit"]), 4) if per_k[k]["hit"] else 0.0,
            "mrr": round(mean(per_k[k]["mrr"]), 4) if per_k[k]["mrr"] else 0.0,
            "recall": round(mean(per_k[k]["recall"]), 4) if per_k[k]["recall"] else 0.0,
        }
        for k in ks
    }
    report = {
        "backend": _backend_name(),
        "num_samples": len(samples),
        "ks": ks,
        "aggregates": aggregates,
        "details": details,
    }
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def _label_type(s: dict) -> str:
    if s.get("gold_chunk_ids"):
        return "gold_chunk_ids"
    if s.get("gold_source_urls"):
        return "gold_source_urls"
    return "phrase_proxy"


def _backend_name() -> str:
    from src.config import settings
    return settings.retrieval.backend


def _print(report: dict) -> None:
    print(f"\nRetrieval metrics  (backend={report['backend']}, n={report['num_samples']})")
    print("-" * 56)
    print(f"{'k':>4} | {'Hit@k':>8} | {'MRR@k':>8} | {'Recall@k':>9}")
    print("-" * 56)
    for k in report["ks"]:
        a = report["aggregates"][f"k={k}"]
        print(f"{k:>4} | {a['hit_rate']:>8.3f} | {a['mrr']:>8.3f} | {a['recall']:>9.3f}")
    print("-" * 56)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retrieval-quality metrics (Recall/Hit/MRR @k).")
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--k", type=int, nargs="+", default=[1, 3, 5, 10])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    rep = evaluate(args.samples, sorted(args.k), args.out)
    _print(rep)
    print(f"\nWrote {args.out}")
