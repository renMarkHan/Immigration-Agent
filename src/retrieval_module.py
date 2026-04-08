"""
Retrieval module — hybrid BM25 + vector retrieval with metadata filtering.

Owner: Ella Lu (Role A — Data & Retrieval)
Implements hybrid retrieval per D-004:
  - BM25 weight 0.6, vector weight 0.4
  - top_k initial=20, reranked to final=5
  - Metadata filters: province / program / stream / effective_date / source_type

DO NOT change the function signatures without updating orchestrator.py.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from src.schemas import RetrievalRequest, RetrievalResult

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROCESSED_CHUNKS_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "processed" / "chunks.jsonl"
)
# Fallback to old demo file if new file doesn't exist
DEMO_CHUNKS_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "processed" / "chunks.jsonl"
)

# ---------------------------------------------------------------------------
# BM25 parameters (D-004)
# ---------------------------------------------------------------------------
BM25_K1 = 1.5
BM25_B = 0.75
BM25_WEIGHT = 0.6
VECTOR_WEIGHT = 0.4  # reserved for ChromaDB integration


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokenization."""
    return re.findall(r"[a-z0-9]+", text.lower())


# ---------------------------------------------------------------------------
# BM25 scoring
# ---------------------------------------------------------------------------

class BM25Index:
    """Simple in-memory BM25 index over chunk texts."""

    def __init__(self, documents: list[dict]):
        self.documents = documents
        self.doc_tokens: list[list[str]] = []
        self.doc_freqs: list[Counter] = []
        self.avg_dl = 0.0
        self.idf: dict[str, float] = {}
        self._build()

    def _build(self):
        n = len(self.documents)
        if n == 0:
            return

        df: Counter = Counter()
        total_len = 0

        for doc in self.documents:
            text = doc.get("text", "")
            section = str(doc.get("metadata", {}).get("section_or_title", ""))
            # Boost section title by including it twice
            tokens = _tokenize(text) + _tokenize(section) + _tokenize(section)
            freqs = Counter(tokens)
            self.doc_tokens.append(tokens)
            self.doc_freqs.append(freqs)
            total_len += len(tokens)
            for term in freqs:
                df[term] += 1

        self.avg_dl = total_len / n if n else 1.0

        # IDF with smoothing
        for term, freq in df.items():
            self.idf[term] = math.log((n - freq + 0.5) / (freq + 0.5) + 1.0)

    def score(self, query: str, doc_idx: int) -> float:
        """BM25 score for a single document against a query."""
        if doc_idx >= len(self.doc_tokens):
            return 0.0

        query_tokens = _tokenize(query)
        doc_len = len(self.doc_tokens[doc_idx])
        freqs = self.doc_freqs[doc_idx]
        score = 0.0

        for term in query_tokens:
            if term not in self.idf:
                continue
            tf = freqs.get(term, 0)
            idf = self.idf[term]
            numerator = tf * (BM25_K1 + 1)
            denominator = tf + BM25_K1 * (1 - BM25_B + BM25_B * doc_len / self.avg_dl)
            score += idf * numerator / denominator

        return score

    def rank(self, query: str, top_k: int = 20) -> list[tuple[int, float]]:
        """Return top-k (doc_idx, score) pairs sorted descending."""
        scores = []
        for i in range(len(self.documents)):
            s = self.score(query, i)
            if s > 0:
                scores.append((i, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# ---------------------------------------------------------------------------
# Chunk loading
# ---------------------------------------------------------------------------

def _load_chunks() -> list[dict]:
    """Load chunk records from the processed JSONL file."""
    target = PROCESSED_CHUNKS_FILE if PROCESSED_CHUNKS_FILE.exists() else DEMO_CHUNKS_FILE
    if not target.exists():
        return []
    rows = []
    with open(target) as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    return rows


# ---------------------------------------------------------------------------
# Metadata filtering (D-004)
# ---------------------------------------------------------------------------

def _filter_passes(row: dict, request: RetrievalRequest) -> bool:
    """Return True if the chunk passes all active metadata filters."""
    md = row.get("metadata", {})
    if request.province and md.get("province") and md["province"] != request.province:
        return False
    if request.program and md.get("program") and md["program"] != request.program:
        return False
    if request.stream and md.get("stream") and md["stream"] != request.stream:
        return False
    if request.source_type and md.get("source_type") and md["source_type"] != request.source_type:
        return False
    return True


# ---------------------------------------------------------------------------
# Public retrieval API
# ---------------------------------------------------------------------------

def retrieve(request: RetrievalRequest) -> list[RetrievalResult]:
    """
    Return ranked RetrievalResult list (length <= request.top_k_final).

    Pipeline:
    1. Load all chunks from processed JSONL.
    2. Apply metadata filters.
    3. Build BM25 index over filtered chunks.
    4. Score and rank by BM25 (vector scoring reserved for ChromaDB integration).
    5. Return top_k_final results with citation metadata.
    """
    all_chunks = _load_chunks()

    # Step 1: metadata filter
    filtered = [row for row in all_chunks if _filter_passes(row, request)]
    if not filtered:
        # Fall back to unfiltered if filters are too strict
        filtered = all_chunks

    if not filtered:
        return []

    # Step 2: BM25 scoring
    bm25 = BM25Index(filtered)
    ranked = bm25.rank(request.query, top_k=request.top_k_initial)

    # Step 3: Take top_k_final (reranker placeholder — currently just top BM25)
    selected = ranked[: request.top_k_final]

    # Step 4: Build results
    results: list[RetrievalResult] = []
    for doc_idx, score in selected:
        row = filtered[doc_idx]
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