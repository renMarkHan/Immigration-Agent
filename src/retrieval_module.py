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
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection

from src.policy_tool_module import normalize_section_or_title
from src.schemas import RetrievalRequest, RetrievalResult

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROCESSED_CHUNKS_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "processed" / "chunks.jsonl"
)
CHROMA_DIR = Path(__file__).resolve().parent.parent / "chroma_db"
CHROMA_COLLECTION = "policy_chunks"

# ---------------------------------------------------------------------------
# BM25 parameters (D-004)
# ---------------------------------------------------------------------------
BM25_K1 = 1.5
BM25_B = 0.75
BM25_WEIGHT = 0.6
VECTOR_WEIGHT = 0.4

# Reranker weights (post-hybrid stage)
RERANK_HYBRID_WEIGHT = 0.70
RERANK_COVERAGE_WEIGHT = 0.25
RERANK_PHRASE_BOOST = 0.05


# ---------------------------------------------------------------------------
# Chroma runtime cache
# ---------------------------------------------------------------------------
_CHROMA_CLIENT: chromadb.PersistentClient | None = None
_CHROMA_COLLECTION: Collection | None = None
_CHROMA_INDEXED_COUNT: int = -1


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokenization."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _normalize_scores(raw: dict[str, float]) -> dict[str, float]:
    """Min-max normalize a score dict to [0, 1]."""
    if not raw:
        return {}
    vals = list(raw.values())
    lo, hi = min(vals), max(vals)
    if math.isclose(lo, hi):
        return {k: 1.0 for k in raw}
    return {k: (v - lo) / (hi - lo) for k, v in raw.items()}


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
            section = normalize_section_or_title(doc.get("metadata", {}).get("section_or_title", ""))
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
    if not PROCESSED_CHUNKS_FILE.exists():
        return []
    rows = []
    with open(PROCESSED_CHUNKS_FILE, encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    return rows


def _sanitize_metadata_for_chroma(md: dict[str, Any]) -> dict[str, Any]:
    """Ensure Chroma metadata values are scalar and non-null."""
    clean: dict[str, Any] = {}
    for k, v in md.items():
        if v is None:
            clean[k] = "unknown"
        elif isinstance(v, (str, int, float, bool)):
            clean[k] = v
        else:
            clean[k] = str(v)
    return clean


def _get_chroma_collection() -> Collection:
    """Get (or initialize) the persistent Chroma collection."""
    global _CHROMA_CLIENT, _CHROMA_COLLECTION
    if _CHROMA_CLIENT is None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _CHROMA_CLIENT = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if _CHROMA_COLLECTION is None:
        _CHROMA_COLLECTION = _CHROMA_CLIENT.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
    return _CHROMA_COLLECTION


def _rebuild_chroma_index(rows: list[dict]) -> Collection:
    """Rebuild the vector index from processed chunks."""
    global _CHROMA_COLLECTION, _CHROMA_INDEXED_COUNT
    collection = _get_chroma_collection()
    if collection.count() > 0:
        _CHROMA_CLIENT.delete_collection(CHROMA_COLLECTION)
        _CHROMA_COLLECTION = _CHROMA_CLIENT.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        collection = _CHROMA_COLLECTION

    if not rows:
        _CHROMA_INDEXED_COUNT = 0
        return collection

    ids = [str(r.get("chunk_id", "")) for r in rows]
    docs = [str(r.get("text", "")) for r in rows]
    metas = [_sanitize_metadata_for_chroma(r.get("metadata", {})) for r in rows]

    batch_size = 500
    for i in range(0, len(rows), batch_size):
        collection.add(
            ids=ids[i:i + batch_size],
            documents=docs[i:i + batch_size],
            metadatas=metas[i:i + batch_size],
        )

    _CHROMA_INDEXED_COUNT = len(rows)
    return collection


def _ensure_chroma_index(rows: list[dict]) -> Collection:
    """Ensure Chroma index matches current processed chunk corpus."""
    collection = _get_chroma_collection()
    global _CHROMA_INDEXED_COUNT
    target_count = len(rows)

    # On the first query in a fresh process, reuse the already-persisted index
    # when its size matches the corpus instead of re-embedding every chunk.
    # Without this, each server restart re-embeds the full corpus (~30s) on the
    # first request, which can push a single turn past the frontend timeout.
    if _CHROMA_INDEXED_COUNT == -1:
        try:
            persisted = collection.count()
        except Exception:
            persisted = 0
        if target_count > 0 and persisted == target_count:
            _CHROMA_INDEXED_COUNT = target_count
            return collection

    # Rebuild when corpus size changed or first use.
    if _CHROMA_INDEXED_COUNT != target_count:
        return _rebuild_chroma_index(rows)
    return collection


def build_index() -> int:
    """(Re)build the persistent Chroma vector index from the processed chunks.

    Public entry point used by the ingestion / draw-data scripts and the
    ``python -m src.retrieval_module --build`` CLI. Returns the number of
    chunks indexed.
    """
    rows = _load_chunks()
    _rebuild_chroma_index(rows)
    return len(rows)


def _vector_rank(query: str, candidate_rows: list[dict], top_k: int) -> dict[str, float]:
    """Vector retrieval scores from Chroma over candidate row IDs."""
    if not candidate_rows:
        return {}

    # Build/refresh full index, then filter by candidate IDs for this request.
    collection = _ensure_chroma_index(_load_chunks())
    candidate_ids = {str(r.get("chunk_id", "")) for r in candidate_rows}

    # Query wider than top_k before metadata filtering to keep recall.
    n_results = max(top_k * 4, 20)
    out = collection.query(query_texts=[query], n_results=n_results, include=["distances", "ids"])

    ids = out.get("ids", [[]])[0]
    dists = out.get("distances", [[]])[0]
    scores: dict[str, float] = {}

    for cid, dist in zip(ids, dists):
        if cid not in candidate_ids:
            continue
        # Convert cosine distance to similarity-like score.
        sim = 1.0 / (1.0 + float(dist))
        scores[cid] = sim

    return scores


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


def _rerank_score(query: str, row: dict, hybrid_score: float) -> float:
    """Final reranker score combining hybrid rank + query coverage features."""
    query_tokens = set(_tokenize(query))
    text = str(row.get("text", ""))
    section = normalize_section_or_title(row.get("metadata", {}).get("section_or_title", ""))
    doc_tokens = set(_tokenize(text) + _tokenize(section))

    if not query_tokens:
        coverage = 0.0
    else:
        coverage = len(query_tokens & doc_tokens) / len(query_tokens)

    phrase_boost = 1.0 if query.lower() in text.lower() else 0.0

    return (
        RERANK_HYBRID_WEIGHT * hybrid_score
        + RERANK_COVERAGE_WEIGHT * coverage
        + RERANK_PHRASE_BOOST * phrase_boost
    )


# ---------------------------------------------------------------------------
# Public retrieval API
# ---------------------------------------------------------------------------

def retrieve(request: RetrievalRequest) -> list[RetrievalResult]:
    """
    Return ranked RetrievalResult list (length <= request.top_k_final).

    Pipeline:
    1. Load all chunks from processed JSONL.
    2. Apply metadata filters.
    3. Score with BM25 and vector similarity (ChromaDB).
    4. Blend scores (BM25 0.6 + vector 0.4), then rerank.
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
    bm25_ranked = bm25.rank(request.query, top_k=request.top_k_initial)
    bm25_raw: dict[str, float] = {
        str(filtered[idx].get("chunk_id", "")): score for idx, score in bm25_ranked
    }

    # Step 3: Vector scoring via Chroma (fallback to BM25-only if unavailable)
    vector_raw: dict[str, float] = {}
    try:
        vector_raw = _vector_rank(request.query, filtered, top_k=request.top_k_initial)
    except Exception:
        vector_raw = {}

    bm25_norm = _normalize_scores(bm25_raw)
    vector_norm = _normalize_scores(vector_raw)

    # Step 4: Hybrid blending on union of candidates
    by_id: dict[str, dict] = {str(r.get("chunk_id", "")): r for r in filtered}
    candidate_ids = set(bm25_norm) | set(vector_norm)
    if not candidate_ids:
        # Last-resort fallback: take first filtered docs with zero scores.
        candidate_ids = {str(r.get("chunk_id", "")) for r in filtered[: request.top_k_initial]}

    hybrid: list[tuple[str, float]] = []
    for cid in candidate_ids:
        h = BM25_WEIGHT * bm25_norm.get(cid, 0.0) + VECTOR_WEIGHT * vector_norm.get(cid, 0.0)
        hybrid.append((cid, h))
    hybrid.sort(key=lambda x: x[1], reverse=True)
    hybrid = hybrid[: request.top_k_initial]

    # Step 5: Explicit reranker over hybrid candidates
    reranked: list[tuple[str, float]] = []
    for cid, hscore in hybrid:
        row = by_id.get(cid)
        if row is None:
            continue
        reranked.append((cid, _rerank_score(request.query, row, hscore)))
    reranked.sort(key=lambda x: x[1], reverse=True)
    selected = reranked[: request.top_k_final]

    # Step 6: Build results
    results: list[RetrievalResult] = []
    for cid, score in selected:
        row = by_id[cid]
        md = row.get("metadata", {})
        normalized_section = normalize_section_or_title(md.get("section_or_title"))
        results.append(
            RetrievalResult(
                chunk_id=cid or "unknown",
                text=row.get("text", ""),
                score=score,
                metadata=md,
                citation={
                    "source_url": md.get("source_url", "unknown"),
                    "section_or_title": normalized_section,
                    "effective_date_or_last_updated_or_unknown": md.get(
                        "effective_date_or_last_updated_or_unknown", "unknown"
                    ),
                    "accessed_at": md.get("accessed_at", "unknown"),
                },
            )
        )
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Retrieval index utilities.")
    parser.add_argument(
        "--build",
        action="store_true",
        help="(Re)build the Chroma vector index from processed chunks.",
    )
    args = parser.parse_args()
    if args.build:
        n = build_index()
        print(f"[retrieval] Index built — {n} chunks indexed.")
    else:
        parser.print_help()