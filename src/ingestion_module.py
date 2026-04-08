"""
Data ingestion / indexing module stub.

Owner: Chao Tang (Role D — Data & Ingestion)
Handles: scraping, chunking, embedding, loading into ChromaDB.

DO NOT change the function signatures without updating orchestrator.py.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
PROCESSED_CHUNKS_FILE = PROCESSED_DIR / "demo_chunks.jsonl"


def _seed_demo_chunks_for_source(source_url: str) -> list[dict]:
    """
    Build a minimal demo chunk list for the specified source.

    This is a process demo for teammates, not the final crawler/parser.
    """
    if source_url.rstrip("/") == "https://www.ontario.ca/page/oinp-masters-graduate-stream":
        return [
            {
                "chunk_id": "oinp-masters-requirements-001",
                "text": (
                    "Ontario Immigrant Nominee Program Masters Graduate Stream "
                    "requires applicants to satisfy eligibility requirements such as "
                    "education in Ontario, language level, residency intent, and legal status "
                    "at application time."
                ),
                "metadata": {
                    "province": "Ontario",
                    "program": "OINP",
                    "stream": "Masters Graduate Stream",
                    "source_type": "official_webpage",
                    "effective_date": "unknown",
                    "source_url": source_url,
                    "section_or_title": "Requirements",
                    "effective_date_or_last_updated_or_unknown": "unknown",
                    "accessed_at": date.today().isoformat(),
                },
            }
        ]

    return []


def ingest(source_url: str) -> int:
    """
    Scrape, chunk, embed and store documents from source_url.
    Returns number of chunks stored.

    TODO (Chao): replace with full crawler/cleaner/chunker/indexer pipeline.

    Current behavior:
      - Materializes a demonstrative processed chunk for the OINP Masters page.
      - Persists it in local JSONL for retrieval teammates to test query flow.
    """
    chunks = _seed_demo_chunks_for_source(source_url)
    if not chunks:
        return 0

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    existing_ids = set()
    if PROCESSED_CHUNKS_FILE.exists():
        with open(PROCESSED_CHUNKS_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                existing_ids.add(row.get("chunk_id"))

    written = 0
    with open(PROCESSED_CHUNKS_FILE, "a") as f:
        for chunk in chunks:
            if chunk["chunk_id"] in existing_ids:
                continue
            f.write(json.dumps(chunk, ensure_ascii=True) + "\n")
            written += 1

    return written
