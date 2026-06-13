"""
Context builder — token-budget-aware assembly of retrieved evidence.

The MVP injected the full text of every top-k chunk into the prompt with no
size control, no de-duplication, and no prioritization. As corpora and k grow
that overruns the model's context window and dilutes the signal.

This module implements adaptive context assembly (Decision D-011):
  - Compute a token budget from the model's context window, minus the system
    prompt, conversation history, response-format block, and output reservation
  - De-duplicate near-identical evidence (overlapping chunks share content)
  - Pack evidence in relevance order, truncating the tail chunk to fit rather
    than dropping it abruptly, and stop once the budget is consumed
  - Always keep citation metadata intact for the chunks that are included
  - Structured tool outputs are small and high-value: they are packed first
"""

from __future__ import annotations

import re

from src.config import settings
from src.schemas import RetrievalResult, ToolResult

# Reserve for system prompt + format instructions + query + a safety margin,
# in tokens. Conversation history is accounted for separately by the caller.
_BASE_RESERVE_TOKENS = 1500
_MIN_CHUNK_TOKENS = 60  # don't include a chunk truncated below this


def estimate_tokens(text: str) -> int:
    """Rough token estimate for mixed English/Chinese text.

    English averages ~4 chars/token; CJK characters are ~1 token each.
    """
    if not text:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    other = len(text) - cjk
    return cjk + max(1, other // 4)


def evidence_budget_tokens(history_tokens: int = 0) -> int:
    """Token budget available for retrieved evidence on this turn."""
    window = settings.llm.context_window_tokens
    reserve = settings.llm.max_output_tokens + _BASE_RESERVE_TOKENS + history_tokens
    return max(1000, window - reserve)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to approximately max_tokens, on a sentence boundary."""
    if estimate_tokens(text) <= max_tokens:
        return text
    # Approximate char budget (treat as English-ish; CJK truncation is safe too).
    approx_chars = max_tokens * 4
    clipped = text[:approx_chars]
    # Prefer to cut at the last sentence end for readability.
    cut = max(clipped.rfind(". "), clipped.rfind("\n"))
    if cut > approx_chars * 0.5:
        clipped = clipped[: cut + 1]
    return clipped.rstrip() + " […]"


def _dedup(results: list[RetrievalResult]) -> list[RetrievalResult]:
    """Drop chunks with duplicate content_hash or identical normalized text."""
    seen: set[str] = set()
    out: list[RetrievalResult] = []
    for r in results:
        key = (r.metadata or {}).get("content_hash")
        if not key:
            key = re.sub(r"\s+", " ", r.text).strip().lower()[:200]
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _format_citation(r: RetrievalResult) -> str:
    c = r.citation
    if not c:
        return ""
    return (
        f"  Source: {c.source_url}\n"
        f"  Section: {c.section_or_title}\n"
        f"  Effective/Updated: {c.effective_date_or_last_updated_or_unknown}\n"
        f"  Accessed: {c.accessed_at}"
    )


def assemble_evidence(
    results: list[RetrievalResult],
    tool_results: list[ToolResult],
    history_tokens: int = 0,
) -> str:
    """Assemble a budget-bounded, de-duplicated evidence block."""
    import json

    budget = evidence_budget_tokens(history_tokens)
    lines: list[str] = []
    used = 0

    # 1) Tool outputs first (small, structured, high-value).
    for j, t in enumerate(tool_results, 1):
        output = t.output if hasattr(t, "output") else getattr(t, "output_data", None)
        error = t.error if hasattr(t, "error") else getattr(t, "error_msg", None)
        if error is None:
            block = f"[Tool Result {j}: {t.tool_name}]\n  Output: {json.dumps(output, indent=2, ensure_ascii=False)}"
        else:
            block = f"[Tool Result {j}: {t.tool_name} — ERROR]\n  Error: {error}"
        tok = estimate_tokens(block)
        if used + tok > budget:
            break
        lines.append(block)
        used += tok

    # 2) Retrieved chunks in relevance order, de-duplicated, budget-packed.
    for i, r in enumerate(_dedup(results), 1):
        citation_str = _format_citation(r)
        header = f"[Evidence {i}]\n  Text: "
        overhead = estimate_tokens(header + "\n" + citation_str)
        remaining = budget - used - overhead
        if remaining < _MIN_CHUNK_TOKENS:
            break
        text = _truncate_to_tokens(r.text, remaining)
        block = f"{header}{text}\n{citation_str}"
        lines.append(block)
        used += estimate_tokens(block)

    return "\n\n".join(lines) if lines else "(no evidence)"
