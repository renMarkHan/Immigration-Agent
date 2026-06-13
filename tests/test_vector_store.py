"""
Integration test for the pgvector vector store.

Runs against a real Postgres+pgvector instance (provided by CI service or a
local DB) using the deterministic fake embedding provider, so it is fast and
needs no model downloads. Skipped automatically when no DB is reachable.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("EMBEDDING_PROVIDER", "fake")
os.environ.setdefault("EMBEDDING_DIMENSION", "64")

from src import embeddings  # noqa: E402
from src.embeddings import FakeEmbedding, set_embedding_provider  # noqa: E402


@pytest.fixture(scope="module")
def store():
    set_embedding_provider(FakeEmbedding(dim=64))
    from src import vector_store as vs

    try:
        vs.init_schema(dim=64)
    except vs.VectorStoreUnavailable as exc:
        pytest.skip(f"pgvector not available: {exc}")
    vs.delete_all()
    return vs


def _rows():
    return [
        {"chunk_id": "c1", "text": "Express Entry CRS minimum score for the latest draw.",
         "metadata": {"doc_id": "ee", "program": "Express Entry", "source_url": "u1",
                      "section_or_title": "CRS", "content_hash": "h1", "language": "en"}},
        {"chunk_id": "c2", "text": "Provincial Nominee Program streams in Ontario OINP.",
         "metadata": {"doc_id": "pnp", "program": "PNP", "province": "Ontario",
                      "source_url": "u2", "section_or_title": "OINP", "content_hash": "h2",
                      "language": "en"}},
        {"chunk_id": "c3", "text": "Language test CLB requirements and equivalency charts.",
         "metadata": {"doc_id": "lang", "program": "Express Entry", "source_url": "u3",
                      "section_or_title": "Language", "content_hash": "h3", "language": "en"}},
    ]


def test_upsert_and_count(store):
    n = store.upsert_chunks(_rows())
    assert n == 3
    assert store.count() == 3


def test_upsert_is_idempotent(store):
    store.upsert_chunks(_rows())
    store.upsert_chunks(_rows())  # re-upsert same ids
    assert store.count() == 3


def test_dense_search_returns_results(store):
    store.upsert_chunks(_rows())
    out = store.dense_search("CRS score Express Entry", k=3)
    assert out, "dense search returned nothing"
    assert all("chunk_id" in r and "score" in r for r in out)


def test_keyword_search_matches_terms(store):
    store.upsert_chunks(_rows())
    out = store.keyword_search("Provincial Nominee Ontario", k=3)
    ids = {r["chunk_id"] for r in out}
    assert "c2" in ids


def test_hybrid_search_and_filter(store):
    store.upsert_chunks(_rows())
    out = store.hybrid_search("language requirements", k=3)
    assert out
    filtered = store.hybrid_search("streams", k=3, filters={"province": "Ontario"})
    assert all((r["metadata"].get("province") == "Ontario") for r in filtered)


def test_delete_by_doc(store):
    store.upsert_chunks(_rows())
    removed = store.delete_by_doc("pnp")
    assert removed >= 1
    ids = {r["chunk_id"] for r in store.dense_search("anything", k=10)}
    assert "c2" not in ids
