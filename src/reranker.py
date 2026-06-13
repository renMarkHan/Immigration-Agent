"""
Reranker — cross-encoder reranking of retrieval candidates.

The MVP used a hand-rolled lexical reranker (token coverage + phrase boost).
For production we add a true multilingual cross-encoder, bge-reranker-v2-m3,
which jointly encodes (query, passage) and scores relevance far more
accurately than score blending alone (Decision D-011).

Pluggable and lazy: the model loads on first use; when the reranker is
disabled or the library is unavailable, an identity reranker preserves the
input order so the pipeline still works.
"""

from __future__ import annotations

import logging

from src.config import settings

log = logging.getLogger("reranker")

_RERANKER = None


class _IdentityReranker:
    """No-op reranker: returns candidates in their original order."""

    def rerank(self, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        return candidates[:top_k]


class _CrossEncoderReranker:
    """bge-reranker-v2-m3 via FlagEmbedding.FlagReranker (lazy-loaded)."""

    def __init__(self) -> None:
        self._model = None

    def _load(self):
        if self._model is None:
            from FlagEmbedding import FlagReranker  # type: ignore

            use_fp16 = settings.reranker.device != "cpu"
            self._model = FlagReranker(settings.reranker.model, use_fp16=use_fp16)
        return self._model

    def rerank(self, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        if not candidates:
            return []
        model = self._load()
        pairs = [[query, c.get("text", "")] for c in candidates]
        scores = model.compute_score(pairs, normalize=True)
        if not isinstance(scores, list):
            scores = [scores]
        ranked = sorted(zip(candidates, scores), key=lambda cs: cs[1], reverse=True)
        out = []
        for cand, score in ranked[:top_k]:
            rec = dict(cand)
            rec["score"] = float(score)
            rec["rerank_score"] = float(score)
            out.append(rec)
        return out


def get_reranker():
    """Return the active reranker (process singleton)."""
    global _RERANKER
    if _RERANKER is None:
        if not settings.reranker.enabled:
            _RERANKER = _IdentityReranker()
        else:
            try:
                _RERANKER = _CrossEncoderReranker()
            except Exception as exc:  # pragma: no cover
                log.warning("cross-encoder unavailable, using identity reranker: %s", exc)
                _RERANKER = _IdentityReranker()
    return _RERANKER


def set_reranker(reranker) -> None:
    """Override the active reranker (tests)."""
    global _RERANKER
    _RERANKER = reranker


def rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """Rerank candidate rows ({chunk_id, text, metadata, ...}) for a query."""
    try:
        return get_reranker().rerank(query, candidates, top_k)
    except Exception as exc:  # pragma: no cover - never break retrieval
        log.warning("rerank failed (%s); returning input order", exc)
        return candidates[:top_k]
