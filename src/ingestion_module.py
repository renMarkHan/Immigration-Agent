"""
Data ingestion module — scrape, clean, chunk, and persist official source documents.

Owner: Ella Lu (Role A — Data & Retrieval)
Handles: scraping official IRCC + OINP pages, cleaning HTML, section-based chunking,
         metadata attachment, and persistence to JSONL for downstream indexing.

DO NOT change the function signatures without updating orchestrator.py.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from src.policy_tool_module import normalize_section_or_title

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SOURCES_DIR = DATA_DIR / "sources"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
PROCESSED_CHUNKS_FILE = PROCESSED_DIR / "chunks.jsonl"
URL_REGISTRY_FILE = SOURCES_DIR / "url_registry.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_CHUNK_CHARS = 1500  # target max characters per chunk
MIN_CHUNK_CHARS = 100   # skip chunks smaller than this
REQUEST_TIMEOUT = 30
REQUEST_DELAY = 1.0  # polite delay between requests (seconds)

USER_AGENT = (
    "Mozilla/5.0 (compatible; ImmigrationAgentBot/1.0; "
    "+https://github.com/renMarkHan/Immigration-Agent)"
)


# ---------------------------------------------------------------------------
# HTML cleaning
# ---------------------------------------------------------------------------

def _strip_html_tags(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"&\w+;", "", text)
    # collapse blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # collapse horizontal whitespace on each line
    lines = [re.sub(r"[ \t]+", " ", line.strip()) for line in text.splitlines()]
    return "\n".join(lines).strip()


def _extract_main_content(html: str) -> str:
    """Try to extract the <main> or <article> body; fall back to full page."""
    for tag in ("main", "article"):
        pattern = re.compile(rf"<{tag}[^>]*>(.*?)</{tag}>", re.DOTALL | re.IGNORECASE)
        match = pattern.search(html)
        if match:
            return _strip_html_tags(match.group(1))
    return _strip_html_tags(html)


# ---------------------------------------------------------------------------
# Section-based chunking
# ---------------------------------------------------------------------------

def _split_into_sections(text: str) -> list[dict[str, str]]:
    """
    Split cleaned text into section chunks.

    Heuristic: lines that look like headers (short, no trailing period,
    often followed by substantive text) start new sections.
    We also split on double newlines within long sections.
    """
    lines = text.splitlines()
    sections: list[dict[str, str]] = []
    current_title = "Overview"
    current_body_lines: list[str] = []

    def _flush():
        body = "\n".join(current_body_lines).strip()
        if len(body) >= MIN_CHUNK_CHARS:
            sections.append({"title": current_title, "body": body})

    for line in lines:
        stripped = line.strip()
        if not stripped:
            current_body_lines.append("")
            continue

        # Heuristic: header-like line
        is_header = (
            len(stripped) < 120
            and not stripped.endswith(".")
            and not stripped.endswith(",")
            and not stripped.startswith("•")
            and not stripped.startswith("-")
            and not stripped[0].islower()
            and len(stripped.split()) <= 15
            and not any(c.isdigit() and len(stripped) > 80 for c in stripped)
        )

        if is_header and len("\n".join(current_body_lines).strip()) > MIN_CHUNK_CHARS:
            _flush()
            current_title = stripped
            current_body_lines = []
        else:
            current_body_lines.append(stripped)

    _flush()
    return sections


def _break_long_section(title: str, body: str, max_chars: int = MAX_CHUNK_CHARS) -> list[dict[str, str]]:
    """Break a long section body into smaller chunks on paragraph boundaries."""
    if len(body) <= max_chars:
        return [{"title": title, "body": body}]

    paragraphs = re.split(r"\n{2,}", body)
    chunks: list[dict[str, str]] = []
    current_parts: list[str] = []
    current_len = 0
    part_idx = 1

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if current_len + len(para) > max_chars and current_parts:
            chunks.append({
                "title": f"{title} (part {part_idx})",
                "body": "\n\n".join(current_parts),
            })
            part_idx += 1
            current_parts = []
            current_len = 0
        current_parts.append(para)
        current_len += len(para) + 2

    if current_parts:
        suffix = f" (part {part_idx})" if part_idx > 1 else ""
        chunks.append({
            "title": f"{title}{suffix}",
            "body": "\n\n".join(current_parts),
        })

    return chunks


# ---------------------------------------------------------------------------
# Chunk ID generation
# ---------------------------------------------------------------------------

def _make_chunk_id(source_id: str, section_title: str, part_index: int) -> str:
    """Deterministic chunk ID from source + section + part."""
    raw = f"{source_id}::{section_title}::{part_index}"
    short_hash = hashlib.sha256(raw.encode()).hexdigest()[:8]
    slug = re.sub(r"[^a-z0-9]+", "-", source_id.lower()).strip("-")
    return f"{slug}-{short_hash}"


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _fetch_page(url: str) -> str | None:
    """Fetch a single URL and return raw HTML, or None on failure."""
    try:
        with httpx.Client(follow_redirects=True, timeout=REQUEST_TIMEOUT) as client:
            resp = client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        print(f"[ingestion] WARN: failed to fetch {url}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest(source_url: str, source_meta: dict[str, Any] | None = None) -> int:
    """
    Scrape, clean, chunk and persist a single source URL.
    Returns the number of NEW chunks written (skips duplicates).

    source_meta: optional dict with keys like province, program, stream, source_id.
                 If not provided, sensible defaults are inferred.
    """
    meta = source_meta or {}
    source_id = meta.get("id", re.sub(r"https?://", "", source_url).replace("/", "_")[:60])

    html = _fetch_page(source_url)
    if html is None:
        return 0

    # Save raw HTML
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_file = RAW_DIR / f"{source_id}.html"
    raw_file.write_text(html, encoding="utf-8")

    # Extract and clean text
    text = _extract_main_content(html)
    if len(text) < MIN_CHUNK_CHARS:
        print(f"[ingestion] WARN: very little text extracted from {source_url}")
        return 0

    # Section-based chunking
    raw_sections = _split_into_sections(text)
    chunks: list[dict[str, str]] = []
    for sec in raw_sections:
        chunks.extend(_break_long_section(sec["title"], sec["body"]))

    if not chunks:
        print(f"[ingestion] WARN: no chunks produced from {source_url}")
        return 0

    # Build chunk records with metadata
    today = date.today().isoformat()
    records: list[dict] = []
    for idx, chunk in enumerate(chunks):
        normalized_title = normalize_section_or_title(chunk["title"], fallback="Overview")
        chunk_id = _make_chunk_id(source_id, normalized_title, idx)
        records.append({
            "chunk_id": chunk_id,
            "text": chunk["body"],
            "metadata": {
                "province": meta.get("province"),
                "program": meta.get("program"),
                "stream": meta.get("stream"),
                "source_type": meta.get("source_type", "official_webpage"),
                "source_url": source_url,
                "section_or_title": normalized_title,
                "effective_date_or_last_updated_or_unknown": "unknown",
                "accessed_at": today,
            },
        })

    # Persist (append, skip existing IDs)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    existing_ids: set[str] = set()
    if PROCESSED_CHUNKS_FILE.exists():
        with open(PROCESSED_CHUNKS_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    existing_ids.add(row.get("chunk_id"))
                except json.JSONDecodeError:
                    continue

    written = 0
    with open(PROCESSED_CHUNKS_FILE, "a") as f:
        for rec in records:
            if rec["chunk_id"] in existing_ids:
                continue
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1

    print(f"[ingestion] {source_url} -> {len(records)} chunks total, {written} new")
    return written


def ingest_all(priority_filter: str | None = "P0") -> int:
    """
    Ingest all sources from the URL registry, optionally filtered by priority.
    Returns total new chunks written.
    """
    if not URL_REGISTRY_FILE.exists():
        print(f"[ingestion] ERROR: registry not found at {URL_REGISTRY_FILE}")
        return 0

    with open(URL_REGISTRY_FILE) as f:
        registry = json.load(f)

    total = 0
    for entry in registry:
        if entry.get("source_type") == "official_tool":
            # skip tools that aren't scrapable content pages
            continue
        if priority_filter and entry.get("priority") != priority_filter:
            continue

        print(f"\n[ingestion] Processing: {entry['page']} ({entry['url']})")
        n = ingest(entry["url"], source_meta=entry)
        total += n
        time.sleep(REQUEST_DELAY)

    print(f"\n[ingestion] Done. Total new chunks: {total}")
    return total


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    pfilter = sys.argv[1] if len(sys.argv) > 1 else None
    if pfilter == "all":
        pfilter = None
    print(f"[ingestion] Running ingest_all(priority_filter={pfilter!r})")
    ingest_all(priority_filter=pfilter)