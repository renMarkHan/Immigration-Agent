"""
src/fetch_draws_data.py — Fetch and index Express Entry draw results.

The IRCC rounds page (ee-rounds.html) loads CRS cutoff data via JavaScript
from a separate JSON API endpoint. Static HTML scraping captures the table
skeleton but NOT the actual numbers. This module fetches that JSON directly
and writes structured chunks to the retrieval index.

Run:
    python -m src.fetch_draws_data            # fetch live, update index
    python -m src.fetch_draws_data --offline  # rebuild from local snapshot only

Owner: Yuhan Ren (Framework) / Ella Lu (Data & Retrieval)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
CHUNKS_FILE = PROCESSED_DIR / "chunks.jsonl"
SNAPSHOT_FILE = RAW_DIR / "ee-rounds-data.json"

DRAWS_JSON_URL = (
    "https://www.canada.ca/content/dam/ircc/documents/json/ee_rounds_4_en.json"
)
SOURCE_URL = (
    "https://www.canada.ca/en/immigration-refugees-citizenship/services/"
    "immigrate-canada/express-entry/rounds-invitations.html"
)
CHUNK_ID_PREFIX = "ee-rounds-data"

# How many recent rounds to summarise in a single "recent draws" chunk
RECENT_ROUNDS_WINDOW = 20


def _make_chunk_id(suffix: str) -> str:
    raw = f"{CHUNK_ID_PREFIX}::{suffix}"
    return f"{CHUNK_ID_PREFIX}-{hashlib.sha256(raw.encode()).hexdigest()[:8]}"


def _fetch_live() -> list[dict] | None:
    """Try to fetch live draw data from IRCC. Returns None on any failure."""
    try:
        import httpx  # type: ignore
        resp = httpx.get(
            DRAWS_JSON_URL,
            headers={"User-Agent": "Mozilla/5.0 (ImmigrationAgentBot/1.0)"},
            timeout=20,
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()
        rounds = data.get("rounds", [])
        print(f"[fetch_draws] Live fetch OK — {len(rounds)} rounds.")
        return rounds
    except Exception as exc:
        print(f"[fetch_draws] Live fetch failed: {exc}")
        return None


def _load_snapshot() -> list[dict]:
    """Load the local static snapshot."""
    if not SNAPSHOT_FILE.exists():
        raise FileNotFoundError(f"Snapshot not found: {SNAPSHOT_FILE}")
    data = json.loads(SNAPSHOT_FILE.read_text())
    rounds = data.get("rounds", [])
    print(f"[fetch_draws] Loaded snapshot — {len(rounds)} rounds.")
    return rounds


def _save_snapshot(rounds: list[dict], accessed_at: str) -> None:
    """Persist fetched rounds back to the local snapshot for offline use."""
    payload = {
        "_note": (
            "Static snapshot of recent Express Entry draw results. "
            "Refresh by running: python -m src.fetch_draws_data"
        ),
        "_source_url": DRAWS_JSON_URL,
        "_accessed_at": accessed_at,
        "rounds": rounds,
    }
    SNAPSHOT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"[fetch_draws] Snapshot saved → {SNAPSHOT_FILE}")


def _rounds_to_chunks(rounds: list[dict], accessed_at: str) -> list[dict]:
    """Convert raw draw records into retrieval-ready chunk dicts."""
    chunks: list[dict] = []

    # ── Chunk 1: summary table of the most recent N draws ────────────────────
    recent = rounds[:RECENT_ROUNDS_WINDOW]
    rows = []
    for r in recent:
        name = r.get("drawName", "Unknown")
        date_str = r.get("drawDateFull", "?")
        crs = r.get("drawCRS", "?")
        size = r.get("drawSize", "?")
        rows.append(f"- {date_str}: {name} — CRS cutoff {crs}, {size} invitations")

    summary = (
        f"Recent Express Entry Draw Results (last {len(recent)} rounds):\n\n"
        + "\n".join(rows)
        + "\n\n"
        "Note: There is no single fixed minimum CRS score. "
        "The cutoff changes every draw based on the pool size, draw type, and "
        "how many invitations IRCC issues. General (No Limit) draws tend to have "
        "lower cutoffs (~488–504). Category-specific draws (CEC, French, Healthcare) "
        "can range from ~336 (French) to ~541 (CEC). "
        "Always check the official rounds page for the latest figure."
    )
    chunks.append({
        "chunk_id": _make_chunk_id("recent-summary"),
        "text": summary,
        "metadata": {
            "province": None,
            "program": "Express Entry",
            "stream": None,
            "source_type": "official_data",
            "source_url": SOURCE_URL,
            "section_or_title": "Recent Express Entry draw results — CRS cutoffs",
            "effective_date_or_last_updated_or_unknown": accessed_at,
            "accessed_at": accessed_at,
        },
    })

    # ── Chunk 2: plain prose explanation of how cutoffs work ─────────────────
    explanation = (
        "How Express Entry CRS cutoffs work:\n\n"
        "IRCC holds rounds of invitations (draws) roughly every two weeks. "
        "In each draw, candidates are ranked by their Comprehensive Ranking System (CRS) score. "
        "IRCC invites a set number of top-ranked candidates and sends them an "
        "Invitation to Apply (ITA) for permanent residence.\n\n"
        "The CRS score of the lowest-ranked person invited is the 'cutoff' for that draw. "
        "This number is NOT a fixed minimum — it varies every round depending on:\n"
        "  1. The size of the Express Entry pool (more candidates → higher competition)\n"
        "  2. The type of draw: 'No Limit' (all programs) draws include more candidates\n"
        "     and often have lower cutoffs than category-based draws.\n"
        "  3. Category draws (e.g. French language, Healthcare, STEM, Trade occupations, "
        "Agriculture, Transport) target specific occupation groups and can have very "
        "different cutoffs from general draws.\n"
        "  4. PNP draws have near-maximum scores (600+) since nominees get +600 CRS points.\n\n"
        "Historical range (approximate, 2024–2026): ~336 (French category) to ~550 (CEC).\n"
        "General 'No Limit' draws: typically ~488–510.\n"
        "CEC-only draws: typically ~515–545.\n\n"
        "To check the latest round, visit: "
        "https://www.canada.ca/en/immigration-refugees-citizenship/services/"
        "immigrate-canada/express-entry/rounds-invitations.html"
    )
    chunks.append({
        "chunk_id": _make_chunk_id("how-cutoffs-work"),
        "text": explanation,
        "metadata": {
            "province": None,
            "program": "Express Entry",
            "stream": None,
            "source_type": "official_data",
            "source_url": SOURCE_URL,
            "section_or_title": "How Express Entry CRS cutoffs work",
            "effective_date_or_last_updated_or_unknown": accessed_at,
            "accessed_at": accessed_at,
        },
    })

    return chunks


def _remove_old_draws_chunks(lines: list[str]) -> list[str]:
    """Remove any existing ee-rounds-data chunks from the chunks file."""
    kept = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("chunk_id", "").startswith(CHUNK_ID_PREFIX):
                continue
        except json.JSONDecodeError:
            pass
        kept.append(line)
    return kept


def update_chunks_file(chunks: list[dict]) -> int:
    """Merge new draw chunks into chunks.jsonl, replacing any old ones."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    existing_lines: list[str] = []
    if CHUNKS_FILE.exists():
        existing_lines = CHUNKS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()

    kept = _remove_old_draws_chunks(existing_lines)
    new_lines = [json.dumps(c, ensure_ascii=False) for c in chunks]
    all_lines = kept + new_lines

    CHUNKS_FILE.write_text("\n".join(all_lines) + "\n", encoding="utf-8")
    print(f"[fetch_draws] chunks.jsonl updated — added {len(chunks)} draw chunks "
          f"({len(all_lines)} total lines).")
    return len(chunks)


def _rebuild_chroma(chunks: list[dict]) -> None:
    """Re-index the updated chunks file into ChromaDB."""
    try:
        from src.retrieval_module import build_index
        build_index()
        print("[fetch_draws] ChromaDB index rebuilt.")
    except Exception as exc:
        print(f"[fetch_draws] WARN: could not rebuild ChromaDB index: {exc}")
        print("  Run manually: python -m src.retrieval_module --build")


def run(offline: bool = False, rebuild_index: bool = True) -> None:
    """Main entry point."""
    accessed_at = date.today().isoformat()

    rounds: list[dict] | None = None
    if not offline:
        rounds = _fetch_live()
        if rounds:
            _save_snapshot(rounds, accessed_at)

    if rounds is None:
        rounds = _load_snapshot()
        snapshot_meta = json.loads(SNAPSHOT_FILE.read_text())
        accessed_at = snapshot_meta.get("_accessed_at", accessed_at)

    chunks = _rounds_to_chunks(rounds, accessed_at)
    update_chunks_file(chunks)

    if rebuild_index:
        _rebuild_chroma(chunks)

    print("[fetch_draws] Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch and index Express Entry draw data.")
    parser.add_argument("--offline", action="store_true",
                        help="Use local snapshot only — no network request.")
    parser.add_argument("--no-rebuild", action="store_true",
                        help="Update chunks.jsonl but skip ChromaDB rebuild.")
    args = parser.parse_args()
    run(offline=args.offline, rebuild_index=not args.no_rebuild)
