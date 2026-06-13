"""
Crawler — resilient page fetching for the ingestion pipeline.

Primary backend is Scrapling (https://github.com/D4Vinci/Scrapling), an
adaptive scraping library that survives layout changes and basic anti-bot
defences (Decision D-011). We fall back to a plain httpx GET when Scrapling
is unavailable, so ingestion never hard-fails on environment differences.

Responsibilities are intentionally narrow: fetch raw HTML + a few transport
signals (status, final URL, fetch time). Content extraction, cleaning, and
chunking happen in ingestion_module.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from src import logging_setup  # noqa: F401  (configures root logging on import)
import logging

log = logging.getLogger("crawler")

USER_AGENT = (
    "Mozilla/5.0 (compatible; ImmigrationNavigatorBot/2.0; "
    "+https://github.com/renMarkHan/Immigration-Agent)"
)
REQUEST_TIMEOUT = 30


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    html: str
    fetched_at: str
    backend: str
    ok: bool = True
    error: str | None = None
    extra: dict = field(default_factory=dict)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Scrapling backend (lazy import; optional dependency)
# ---------------------------------------------------------------------------

def _fetch_scrapling(url: str) -> FetchResult | None:
    """Fetch via Scrapling. Returns None if the library is unavailable."""
    try:
        from scrapling.fetchers import Fetcher  # type: ignore
    except Exception:
        try:
            from scrapling import Fetcher  # type: ignore  (older layout)
        except Exception:
            return None

    try:
        # Scrapling's Fetcher follows redirects and returns an Adaptor object.
        page = Fetcher.get(url, timeout=REQUEST_TIMEOUT, stealthy_headers=True)
        status = int(getattr(page, "status", 200) or 200)
        html = getattr(page, "html_content", None) or getattr(page, "body", None) or str(page)
        final_url = getattr(page, "url", url) or url
        if status < 400 and html:
            return FetchResult(
                url=url, final_url=final_url, status=status, html=html,
                fetched_at=_now_iso(), backend="scrapling", ok=True,
            )
        # Anti-bot block (e.g. 403): escalate to the browser-based fetcher.
        log.info("scrapling HTTP fetch got %s for %s; trying StealthyFetcher", status, url)
    except Exception as exc:
        log.warning("scrapling fetch failed for %s: %s", url, exc)

    return _fetch_scrapling_browser(url)


def _fetch_scrapling_browser(url: str) -> FetchResult | None:
    """Browser-based stealthy fetch (handles JS + anti-bot 403s).

    Requires Scrapling's browser backend (`scrapling install`). Returns None if
    unavailable so callers fall back to httpx.
    """
    try:
        from scrapling.fetchers import StealthyFetcher  # type: ignore
    except Exception:
        return None
    try:
        page = StealthyFetcher.fetch(url, headless=True, network_idle=True, timeout=REQUEST_TIMEOUT * 1000)
        status = int(getattr(page, "status", 200) or 200)
        html = getattr(page, "html_content", None) or getattr(page, "body", None) or str(page)
        final_url = getattr(page, "url", url) or url
        if status < 400 and html:
            return FetchResult(
                url=url, final_url=final_url, status=status, html=html,
                fetched_at=_now_iso(), backend="scrapling-stealthy", ok=True,
            )
    except Exception as exc:
        log.warning("StealthyFetcher failed for %s: %s", url, exc)
    return None


# ---------------------------------------------------------------------------
# httpx fallback
# ---------------------------------------------------------------------------

def _fetch_httpx(url: str) -> FetchResult:
    try:
        with httpx.Client(follow_redirects=True, timeout=REQUEST_TIMEOUT) as client:
            resp = client.get(url, headers={"User-Agent": USER_AGENT})
            return FetchResult(
                url=url,
                final_url=str(resp.url),
                status=resp.status_code,
                html=resp.text,
                fetched_at=_now_iso(),
                backend="httpx",
                ok=resp.status_code < 400,
                error=None if resp.status_code < 400 else f"HTTP {resp.status_code}",
            )
    except Exception as exc:
        return FetchResult(
            url=url, final_url=url, status=0, html="", fetched_at=_now_iso(),
            backend="httpx", ok=False, error=str(exc),
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch(url: str, prefer: str = "scrapling") -> FetchResult:
    """Fetch a single URL with the preferred backend and graceful fallback."""
    if prefer == "scrapling":
        result = _fetch_scrapling(url)
        if result is not None and result.ok:
            return result
    return _fetch_httpx(url)


def fetch_many(urls: list[str], delay: float = 1.0) -> list[FetchResult]:
    """Fetch multiple URLs politely (sequential with a delay)."""
    results = []
    for i, url in enumerate(urls):
        results.append(fetch(url))
        if i < len(urls) - 1:
            time.sleep(delay)
    return results
