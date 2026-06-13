"""
Ingestion pipeline — crawl, extract, clean, chunk, enrich, and index sources.

Production rewrite (Decision D-011). Replaces the MVP's regex HTML stripping
and append-only JSONL with:

  - Scrapling-based fetching with raw-HTML snapshots (src/crawler.py)
  - trafilatura main-content extraction (boilerplate / nav / footer removal)
  - effective-date extraction from canada.ca "Date modified" + meta tags
  - structure-aware recursive chunking WITH overlap (sliding window)
  - per-chunk content-hash de-duplication
  - per-chunk language detection (EN/ZH-aware corpus)
  - rich chunk metadata (doc_id, section hierarchy, provenance, temporal,
    checksum, language, keywords)
  - dual persistence: portable JSONL (BM25 fallback) + pgvector upsert

Public API preserved for callers (demo_ontario_flow, CLI):
    ingest(source_url, source_meta=None) -> int   (new chunks written)
    ingest_all(priority_filter="P0") -> int
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any

from src import crawler, logging_setup  # noqa: F401
from src import vector_store
from src.config import (
    PROCESSED_CHUNKS_FILE,
    PROCESSED_DIR,
    RAW_DIR,
    URL_REGISTRY_FILE,
    settings,
)
from src.policy_tool_module import normalize_section_or_title

log = logging.getLogger("ingestion")

# ---------------------------------------------------------------------------
# Chunking parameters
# ---------------------------------------------------------------------------
MAX_CHUNK_CHARS = 1200       # target max characters per chunk
MIN_CHUNK_CHARS = 120        # drop chunks smaller than this
CHUNK_OVERLAP_CHARS = 180    # sliding-window overlap between adjacent chunks
REQUEST_DELAY = 1.0

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_DATE_MODIFIED_RE = re.compile(
    r"(?:Date modified|Date de modification)\D*?(\d{4}-\d{2}-\d{2})", re.IGNORECASE
)
_META_DATE_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:dcterms\.modified|article:modified_time|'
    r'last-modified)["\'][^>]+content=["\'](\d{4}-\d{2}-\d{2})',
    re.IGNORECASE,
)

_STOPWORDS = {
    "the", "and", "for", "you", "are", "with", "your", "this", "that", "from",
    "will", "can", "may", "must", "have", "has", "not", "all", "any", "use",
    "a", "an", "of", "to", "in", "on", "or", "is", "be", "as", "if", "it",
}


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------

def _extract_markdown(html: str, url: str) -> tuple[str, str | None]:
    """Return (markdown-ish text, page_title) using trafilatura when available."""
    try:
        import trafilatura  # type: ignore

        extracted = trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_formatting=True,
            include_tables=True,
            favor_recall=True,
            with_metadata=False,
        )
        if extracted and len(extracted) >= MIN_CHUNK_CHARS:
            title = None
            try:
                meta = trafilatura.extract_metadata(html)
                title = getattr(meta, "title", None) if meta else None
            except Exception:
                pass
            return extracted, title
    except Exception as exc:
        log.warning("trafilatura unavailable/failed (%s); falling back", exc)

    return _extract_fallback(html), None


def _extract_fallback(html: str) -> str:
    """BeautifulSoup-based extraction; last-resort if trafilatura is missing."""
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        lines = []
        for el in main.find_all(["h1", "h2", "h3", "h4", "li", "p"]):
            text = el.get_text(" ", strip=True)
            if not text:
                continue
            if el.name in ("h1", "h2", "h3", "h4"):
                level = int(el.name[1])
                lines.append(f"{'#' * level} {text}")
            elif el.name == "li":
                lines.append(f"- {text}")
            else:
                lines.append(text)
        return "\n\n".join(lines)
    except Exception:
        # Final fallback: crude tag strip.
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.I)
        text = re.sub(r"<[^>]+>", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract_effective_date(html: str, text: str) -> str:
    """Best-effort extraction of the page's last-updated date."""
    for source in (html, text):
        m = _DATE_MODIFIED_RE.search(source)
        if m:
            return m.group(1)
    m = _META_DATE_RE.search(html)
    if m:
        return m.group(1)
    return "unknown"


# ---------------------------------------------------------------------------
# Structure-aware chunking with overlap
# ---------------------------------------------------------------------------

def _split_sections(markdown: str) -> list[dict[str, Any]]:
    """Split markdown into sections keyed by their heading hierarchy."""
    sections: list[dict[str, Any]] = []
    heading_stack: list[str] = []
    current_title = "Overview"
    current_path: list[str] = []
    buf: list[str] = []

    def flush():
        body = "\n".join(buf).strip()
        if len(body) >= MIN_CHUNK_CHARS:
            sections.append({
                "title": current_title,
                "path": list(current_path),
                "body": body,
            })

    for line in markdown.splitlines():
        hm = _HEADING_RE.match(line.strip())
        if hm:
            flush()
            level = len(hm.group(1))
            title = hm.group(2).strip()
            heading_stack = heading_stack[: level - 1] + [title]
            current_title = title
            current_path = list(heading_stack)
            buf = []
        else:
            buf.append(line)
    flush()
    if not sections:  # no headings detected
        body = markdown.strip()
        if len(body) >= MIN_CHUNK_CHARS:
            sections.append({"title": "Overview", "path": [], "body": body})
    return sections


def _window_split(body: str, max_chars: int, overlap: int) -> list[str]:
    """Recursive/sliding split of a long body, preserving paragraph boundaries
    where possible and adding overlap between adjacent windows."""
    if len(body) <= max_chars:
        return [body]

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > max_chars:
            # Hard-split an oversized paragraph by sentences.
            if current:
                chunks.append(current)
                current = ""
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                if len(current) + len(sent) + 1 > max_chars and current:
                    chunks.append(current)
                    current = current[-overlap:] if overlap else ""
                current = (current + " " + sent).strip()
        elif len(current) + len(para) + 2 > max_chars and current:
            chunks.append(current)
            current = (current[-overlap:] + "\n\n" + para).strip() if overlap else para
        else:
            current = (current + "\n\n" + para).strip()
    if current and len(current) >= MIN_CHUNK_CHARS:
        chunks.append(current)
    elif current and chunks:
        chunks[-1] = (chunks[-1] + "\n\n" + current).strip()
    return chunks


# ---------------------------------------------------------------------------
# Enrichment helpers
# ---------------------------------------------------------------------------

def _content_hash(text: str) -> str:
    norm = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _detect_language(text: str) -> str:
    try:
        from langdetect import detect  # type: ignore

        return detect(text[:1000])
    except Exception:
        # Heuristic: any CJK char -> zh, else en.
        return "zh" if re.search(r"[\u4e00-\u9fff]", text) else "en"


def _keywords(text: str, top_n: int = 8) -> list[str]:
    tokens = [t for t in re.findall(r"[a-z][a-z0-9]{2,}", text.lower()) if t not in _STOPWORDS]
    return [w for w, _ in Counter(tokens).most_common(top_n)]


def _make_chunk_id(doc_id: str, content_hash: str, idx: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", doc_id.lower()).strip("-")[:40]
    return f"{slug}-{content_hash[:8]}-{idx}"


def _token_estimate(text: str) -> int:
    """Rough token estimate (mixed EN/ZH). EN ~4 chars/token; CJK ~1 char/token."""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    other = len(text) - cjk
    return cjk + max(1, other // 4)


# ---------------------------------------------------------------------------
# Per-document ingestion
# ---------------------------------------------------------------------------

def build_records(source_url: str, source_meta: dict[str, Any] | None = None) -> list[dict]:
    """Fetch + extract + chunk + enrich a single URL into chunk records.

    Returns records but does NOT persist (used for testing/preview).
    """
    meta = source_meta or {}
    doc_id = meta.get("id") or re.sub(r"https?://", "", source_url).replace("/", "_")[:60]

    result = crawler.fetch(source_url)
    if not result.ok or not result.html:
        log.warning("fetch failed for %s: %s", source_url, result.error)
        return []

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{doc_id}.html").write_text(result.html, encoding="utf-8")

    markdown, page_title = _extract_markdown(result.html, result.final_url)
    if len(markdown) < MIN_CHUNK_CHARS:
        log.warning("very little content extracted from %s", source_url)
        return []

    effective_date = _extract_effective_date(result.html, markdown)
    accessed_at = date.today().isoformat()
    page_name = meta.get("page") or page_title or doc_id

    records: list[dict] = []
    seen_hashes: set[str] = set()
    idx = 0
    for sec in _split_sections(markdown):
        for body in _window_split(sec["body"], MAX_CHUNK_CHARS, CHUNK_OVERLAP_CHARS):
            body = body.strip()
            if len(body) < MIN_CHUNK_CHARS:
                continue
            chash = _content_hash(body)
            if chash in seen_hashes:
                continue
            seen_hashes.add(chash)
            normalized_title = normalize_section_or_title(sec["title"], fallback="Overview")
            records.append({
                "chunk_id": _make_chunk_id(doc_id, chash, idx),
                "text": body,
                "metadata": {
                    # Provenance
                    "doc_id": doc_id,
                    "source_id": doc_id,
                    "page": page_name,
                    "source_url": result.final_url,
                    "source_type": meta.get("source_type", "official_webpage"),
                    "content_hash": chash,
                    # Hierarchy
                    "section_or_title": normalized_title,
                    "section_path": " > ".join(sec["path"]) if sec["path"] else normalized_title,
                    "part_index": idx,
                    # Domain filters
                    "province": meta.get("province"),
                    "program": meta.get("program"),
                    "stream": meta.get("stream"),
                    # Temporal
                    "effective_date_or_last_updated_or_unknown": effective_date,
                    "accessed_at": accessed_at,
                    "fetched_at": result.fetched_at,
                    # Retrieval aids
                    "language": _detect_language(body),
                    "keywords": _keywords(body),
                    "char_len": len(body),
                    "token_estimate": _token_estimate(body),
                },
            })
            idx += 1
    return records


def _load_existing() -> tuple[list[dict], set[str]]:
    rows: list[dict] = []
    hashes: set[str] = set()
    if PROCESSED_CHUNKS_FILE.exists():
        with open(PROCESSED_CHUNKS_FILE, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rows.append(row)
                ch = (row.get("metadata") or {}).get("content_hash")
                if ch:
                    hashes.add(ch)
    return rows, hashes


def _rewrite_jsonl(rows: list[dict]) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PROCESSED_CHUNKS_FILE.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(PROCESSED_CHUNKS_FILE)


def ingest(source_url: str, source_meta: dict[str, Any] | None = None) -> int:
    """Crawl, process, and index a single URL. Returns NEW chunks written.

    Re-ingesting the same doc_id replaces its previous chunks (true refresh,
    not append-only). Cross-document duplicate content is skipped by hash.
    """
    records = build_records(source_url, source_meta)
    if not records:
        return 0

    doc_id = records[0]["metadata"]["doc_id"]
    existing, existing_hashes = _load_existing()

    # Drop previous chunks for this doc_id (refresh semantics).
    kept = [r for r in existing if (r.get("metadata") or {}).get("doc_id") != doc_id]
    kept_hashes = {(r.get("metadata") or {}).get("content_hash") for r in kept}

    new_records = [r for r in records if r["metadata"]["content_hash"] not in kept_hashes]
    merged = kept + new_records
    _rewrite_jsonl(merged)

    # Upsert into pgvector (best-effort; JSONL is the durable portable copy).
    try:
        vector_store.delete_by_doc(doc_id)
        vector_store.upsert_chunks(new_records)
    except vector_store.VectorStoreUnavailable as exc:
        log.info("vector store unavailable, skipping upsert (JSONL written): %s", exc)
    except Exception as exc:
        log.warning("vector upsert failed for %s: %s", doc_id, exc)

    log.info("%s -> %d chunks (%d new)", source_url, len(records), len(new_records))
    return len(new_records)


def reindex_from_jsonl() -> int:
    """Rebuild the pgvector index from the existing chunks.jsonl WITHOUT crawling.

    Use this when the chunks were already scraped (chunks.jsonl is populated)
    but the vector store is empty or stale — e.g. after a DB rebuild, an
    embedding-model change, or a failed initial upsert. No network requests.
    """
    rows, _ = _load_existing()
    if not rows:
        log.warning("no chunks found in %s — run ingest_all first", PROCESSED_CHUNKS_FILE)
        return 0
    try:
        vector_store.delete_all()
        n = vector_store.upsert_chunks(rows)
    except vector_store.VectorStoreUnavailable as exc:
        log.error("vector store unavailable, cannot reindex: %s", exc)
        return 0
    log.info("reindexed %d chunks from %s into pgvector", n, PROCESSED_CHUNKS_FILE)
    return n


def ingest_all(priority_filter: str | None = "P0") -> int:
    """Ingest all registry sources, optionally filtered by priority."""
    if not URL_REGISTRY_FILE.exists():
        log.error("registry not found at %s", URL_REGISTRY_FILE)
        return 0

    with open(URL_REGISTRY_FILE, encoding="utf-8", errors="ignore") as f:
        registry = json.load(f)

    total = 0
    for entry in registry:
        if entry.get("source_type") == "official_tool":
            continue
        if priority_filter and entry.get("priority") != priority_filter:
            continue
        log.info("processing: %s (%s)", entry.get("page"), entry.get("url"))
        total += ingest(entry["url"], source_meta=entry)
        time.sleep(REQUEST_DELAY)

    log.info("ingest_all done. total new chunks: %d", total)
    return total


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    pfilter = sys.argv[1] if len(sys.argv) > 1 else None
    if pfilter == "reindex":
        # Index existing chunks.jsonl into pgvector WITHOUT re-crawling.
        log.info("running reindex_from_jsonl() — no network crawl")
        reindex_from_jsonl()
    else:
        if pfilter == "all":
            pfilter = None
        log.info("running ingest_all(priority_filter=%r)", pfilter)
        ingest_all(priority_filter=pfilter)
