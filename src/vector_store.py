"""
Vector store — Postgres + pgvector backend (production retrieval layer).

Replaces the MVP ChromaDB index (Decision D-011). Postgres gives us:
  - Durable storage co-located with application data, easy backup/restore
  - Real incremental upserts (ON CONFLICT) instead of full index rebuilds
  - HNSW cosine ANN search via pgvector
  - First-class metadata filtering (typed columns + JSONB)
  - Hybrid search: dense ANN + full-text (tsvector) fused with Reciprocal
    Rank Fusion (RRF) — more robust than fixed linear score blending

Rows in/out keep the MVP shape so downstream code is unchanged:
    {"chunk_id": str, "text": str, "metadata": {...}, ["score": float]}

The English corpus is searched lexically via an `english` tsvector; non-English
(e.g. Chinese) queries are bridged to the English corpus by the multilingual
bge-m3 dense vectors, so both arms contribute.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from src.config import settings
from src import embeddings

# ---------------------------------------------------------------------------
# Lazy psycopg pool + pgvector registration
# ---------------------------------------------------------------------------
_POOL = None
_SCHEMA_READY = False

_FILTER_COLUMNS = ("province", "program", "stream", "source_type", "language")


class VectorStoreUnavailable(RuntimeError):
    """Raised when the Postgres/pgvector backend cannot be reached."""


def _get_pool():
    global _POOL
    if _POOL is None:
        try:
            from psycopg_pool import ConnectionPool
            from pgvector.psycopg import register_vector
        except Exception as exc:  # pragma: no cover - import guard
            raise VectorStoreUnavailable(
                f"psycopg/pgvector not installed: {exc}"
            ) from exc

        def _configure(conn):
            # Bootstrap order matters: register_vector() requires the `vector`
            # type to already exist, so ensure the extension is created on every
            # fresh connection BEFORE registering the adapter. Without this, a
            # brand-new database fails every connection in the pool with
            # "vector type not found in the database".
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            conn.commit()
            register_vector(conn)

        try:
            _POOL = ConnectionPool(
                conninfo=settings.database.url,
                min_size=settings.database.pool_min,
                max_size=settings.database.pool_max,
                configure=_configure,
                open=True,
                timeout=10,
            )
        except Exception as exc:
            raise VectorStoreUnavailable(
                f"cannot connect to Postgres at {settings.database.host}:"
                f"{settings.database.port}: {exc}"
            ) from exc
    return _POOL


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_schema(dim: int | None = None) -> None:
    """Create the extension, table, and indexes if they do not exist."""
    global _SCHEMA_READY
    dim = dim or embeddings.embedding_dimension()
    pool = _get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id        TEXT PRIMARY KEY,
                    doc_id          TEXT,
                    text            TEXT NOT NULL,
                    embedding       vector({dim}),
                    province        TEXT,
                    program         TEXT,
                    stream          TEXT,
                    source_type     TEXT,
                    language        TEXT,
                    source_url      TEXT,
                    section_or_title TEXT,
                    effective_date  TEXT,
                    content_hash    TEXT,
                    metadata        JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    tsv             tsvector
                        GENERATED ALWAYS AS (to_tsvector('english', coalesce(text,''))) STORED,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            # ANN index (cosine). HNSW is built lazily by pgvector on first use.
            cur.execute(
                "CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw "
                "ON chunks USING hnsw (embedding vector_cosine_ops);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv);"
            )
            for col in _FILTER_COLUMNS:
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS chunks_{col}_idx ON chunks ({col});"
                )
            cur.execute("CREATE INDEX IF NOT EXISTS chunks_doc_idx ON chunks (doc_id);")
        conn.commit()
    _SCHEMA_READY = True


def _ensure_schema() -> None:
    if not _SCHEMA_READY:
        init_schema()


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------

def _row_columns(row: dict) -> dict[str, Any]:
    """Extract typed filter columns from a chunk record's metadata."""
    md = row.get("metadata", {}) or {}
    return {
        "doc_id": md.get("doc_id") or md.get("source_id"),
        "province": md.get("province"),
        "program": md.get("program"),
        "stream": md.get("stream"),
        "source_type": md.get("source_type"),
        "language": md.get("language"),
        "source_url": md.get("source_url"),
        "section_or_title": md.get("section_or_title"),
        "effective_date": md.get("effective_date_or_last_updated_or_unknown")
        or md.get("effective_date"),
        "content_hash": md.get("content_hash"),
    }


def upsert_chunks(rows: list[dict], embed: bool = True, batch_size: int = 128) -> int:
    """Insert or update chunk records (idempotent on chunk_id).

    rows: [{"chunk_id", "text", "metadata": {...}}]. Embeddings are computed
    here from `text` unless `embed=False` and rows already carry "embedding".
    Returns the number of rows written.
    """
    _ensure_schema()
    if not rows:
        return 0
    pool = _get_pool()
    written = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        if embed:
            vectors = embeddings.embed_documents([str(r.get("text", "")) for r in batch])
        else:
            vectors = [r.get("embedding") for r in batch]

        params = []
        for r, vec in zip(batch, vectors):
            cols = _row_columns(r)
            params.append((
                str(r["chunk_id"]),
                cols["doc_id"],
                str(r.get("text", "")),
                vec,
                cols["province"], cols["program"], cols["stream"],
                cols["source_type"], cols["language"], cols["source_url"],
                cols["section_or_title"], cols["effective_date"], cols["content_hash"],
                json.dumps(r.get("metadata", {}), ensure_ascii=False),
            ))

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO chunks (
                        chunk_id, doc_id, text, embedding,
                        province, program, stream, source_type, language,
                        source_url, section_or_title, effective_date, content_hash,
                        metadata
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        doc_id = EXCLUDED.doc_id,
                        text = EXCLUDED.text,
                        embedding = EXCLUDED.embedding,
                        province = EXCLUDED.province,
                        program = EXCLUDED.program,
                        stream = EXCLUDED.stream,
                        source_type = EXCLUDED.source_type,
                        language = EXCLUDED.language,
                        source_url = EXCLUDED.source_url,
                        section_or_title = EXCLUDED.section_or_title,
                        effective_date = EXCLUDED.effective_date,
                        content_hash = EXCLUDED.content_hash,
                        metadata = EXCLUDED.metadata,
                        updated_at = now();
                    """,
                    params,
                )
            conn.commit()
        written += len(batch)
    return written


def delete_by_doc(doc_id: str) -> int:
    _ensure_schema()
    pool = _get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE doc_id = %s;", (doc_id,))
            n = cur.rowcount
        conn.commit()
    return n


def delete_all() -> None:
    _ensure_schema()
    pool = _get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE chunks;")
        conn.commit()


def count() -> int:
    _ensure_schema()
    pool = _get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM chunks;")
            return int(cur.fetchone()[0])


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def _build_filter_sql(filters: dict[str, Any] | None) -> tuple[str, list[Any]]:
    """Build a WHERE clause from active equality filters."""
    if not filters:
        return "", []
    clauses, params = [], []
    for col in _FILTER_COLUMNS:
        val = filters.get(col)
        if val:
            clauses.append(f"{col} = %s")
            params.append(val)
    if not clauses:
        return "", []
    return " WHERE " + " AND ".join(clauses), params


def _row_to_record(row: tuple, cols: list[str]) -> dict:
    d = dict(zip(cols, row))
    md = d.get("metadata") or {}
    if isinstance(md, str):
        try:
            md = json.loads(md)
        except Exception:
            md = {}
    return {"chunk_id": d["chunk_id"], "text": d["text"], "metadata": md}


# ---------------------------------------------------------------------------
# Read path: dense + keyword + RRF hybrid
# ---------------------------------------------------------------------------

def dense_search(query: str, k: int, filters: dict[str, Any] | None = None) -> list[dict]:
    """Cosine ANN search. Returns rows ordered by similarity (score in [0,1])."""
    _ensure_schema()
    qvec = list(embeddings.embed_query(query))
    where, params = _build_filter_sql(filters)
    sql = (
        "SELECT chunk_id, text, metadata, "
        "1 - (embedding <=> %s::vector) AS score "
        "FROM chunks" + where +
        " ORDER BY embedding <=> %s::vector LIMIT %s;"
    )
    pool = _get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [qvec, *params, qvec, k])
            rows = cur.fetchall()
    out = []
    for chunk_id, text, md, score in rows:
        rec = _row_to_record((chunk_id, text, md), ["chunk_id", "text", "metadata"])
        rec["score"] = float(score)
        out.append(rec)
    return out


def keyword_search(query: str, k: int, filters: dict[str, Any] | None = None) -> list[dict]:
    """Full-text (tsvector) search using websearch_to_tsquery + ts_rank."""
    _ensure_schema()
    where, params = _build_filter_sql(filters)
    tsq = "websearch_to_tsquery('english', %s)"
    extra = " AND " if where else " WHERE "
    sql = (
        f"SELECT chunk_id, text, metadata, ts_rank(tsv, {tsq}) AS score "
        f"FROM chunks{where}{extra}tsv @@ {tsq} "
        f"ORDER BY score DESC LIMIT %s;"
    )
    pool = _get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [query, *params, query, k])
            rows = cur.fetchall()
    out = []
    for chunk_id, text, md, score in rows:
        rec = _row_to_record((chunk_id, text, md), ["chunk_id", "text", "metadata"])
        rec["score"] = float(score)
        out.append(rec)
    return out


def _rrf_fuse(rankings: list[list[dict]], k_rrf: int, top_k: int) -> list[dict]:
    """Reciprocal Rank Fusion of multiple ranked lists keyed by chunk_id."""
    scores: dict[str, float] = {}
    records: dict[str, dict] = {}
    for ranking in rankings:
        for rank, rec in enumerate(ranking):
            cid = rec["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k_rrf + rank + 1)
            records.setdefault(cid, rec)
    fused = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    out = []
    for cid, s in fused:
        rec = dict(records[cid])
        rec["score"] = s
        out.append(rec)
    return out


def hybrid_search(
    query: str,
    k: int,
    filters: dict[str, Any] | None = None,
    candidate_k: int | None = None,
) -> list[dict]:
    """Dense + keyword retrieval fused with RRF.

    Each arm fetches `candidate_k` candidates; the fused list is truncated to
    `k`. If filters yield nothing, the caller may retry without filters.
    """
    candidate_k = candidate_k or max(k * 4, 20)
    dense = dense_search(query, candidate_k, filters)
    keyword = keyword_search(query, candidate_k, filters)
    if not dense and not keyword:
        return []
    return _rrf_fuse([dense, keyword], settings.retrieval.rrf_k, k)
