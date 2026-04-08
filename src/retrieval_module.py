"""
Retrieval module stub.

Owner: Keqing Wang (Role B — Retrieval)
Implements hybrid BM25 + vector retrieval (D-004):
  - BM25 weight 0.6, vector weight 0.4
  - top_k initial=20, reranked to final=5
  - Metadata filters: province / program / stream / effective_date / source_type

DO NOT change the function signatures without updating orchestrator.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.schemas import RetrievalRequest, RetrievalResult


PROCESSED_CHUNKS_FILE = Path(__file__).resolve().parent.parent / "data" / "processed" / "demo_chunks.jsonl"


def _tokenize(text: str) -> set[str]:
  return set(re.findall(r"[a-z0-9]+", text.lower()))


def _score(query: str, text: str, section: str) -> float:
  query_tokens = _tokenize(query)
  body_tokens = _tokenize(text)
  section_tokens = _tokenize(section)
  if not query_tokens:
    return 0.0

  body_overlap = len(query_tokens & body_tokens)
  section_overlap = len(query_tokens & section_tokens)
  return float(body_overlap + section_overlap * 2)


def _load_chunks() -> list[dict]:
  if not PROCESSED_CHUNKS_FILE.exists():
    return []
  rows = []
  with open(PROCESSED_CHUNKS_FILE) as f:
    for line in f:
      stripped = line.strip()
      if not stripped:
        continue
      rows.append(json.loads(stripped))
  return rows


def _filter_passes(row: dict, request: RetrievalRequest) -> bool:
  md = row.get("metadata", {})
  if request.province and md.get("province") != request.province:
    return False
  if request.program and md.get("program") != request.program:
    return False
  if request.stream and md.get("stream") != request.stream:
    return False
  if request.source_type and md.get("source_type") != request.source_type:
    return False
  return True


def retrieve(request: RetrievalRequest) -> list[RetrievalResult]:
    """
    Return ranked RetrievalResult list (length <= request.top_k_final).

    TODO (Keqing): Replace with real BM25+ChromaDB hybrid retrieval.

    Current behavior:
      - Reads locally ingested demo chunks.
      - Applies lightweight metadata filtering.
      - Uses simple token overlap scoring to illustrate retrieval flow.
    """
    rows = _load_chunks()
    scored = []
    for row in rows:
      if not _filter_passes(row, request):
        continue

      md = row.get("metadata", {})
      section = str(md.get("section_or_title", ""))
      s = _score(request.query, row.get("text", ""), section)
      if s <= 0:
        continue
      scored.append((s, row))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: request.top_k_final]

    results: list[RetrievalResult] = []
    for score, row in selected:
      md = row.get("metadata", {})
      results.append(
        RetrievalResult(
          chunk_id=row.get("chunk_id", "unknown"),
          text=row.get("text", ""),
          score=score,
          metadata=md,
          citation={
            "source_url": md.get("source_url", "unknown"),
            "section_or_title": md.get("section_or_title", "unknown"),
            "effective_date_or_last_updated_or_unknown": md.get(
              "effective_date_or_last_updated_or_unknown", "unknown"
            ),
            "accessed_at": md.get("accessed_at", "unknown"),
          },
        )
      )
    return results
