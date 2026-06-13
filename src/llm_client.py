"""
LLM client — thin wrapper around the OpenAI-compatible endpoint.

Owner: Yuhan Ren (Framework Owner)
All modules call generate() from here; never instantiate the client directly.
"""

from __future__ import annotations

from typing import Any, Iterator

from openai import OpenAI

from src.config import settings

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.llm.api_key, base_url=settings.llm.base_url)
    return _client


def generate(
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    timeout_seconds: float | None = None,
) -> str:
    """
    Call the LLM and return the assistant content string.

    Note: qwen3-30b-a3b-fp8 uses chain-of-thought (reasoning_content).
    We return the final content field; reasoning tokens are discarded.
    """
    client = _get_client()
    resolved_model = model or settings.llm.model
    resolved_timeout = timeout_seconds if timeout_seconds is not None else settings.llm.timeout_seconds

    try:
        response = client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=resolved_timeout,
        )
        choice = response.choices[0]
        # content may be None if all tokens were consumed by reasoning
        return choice.message.content or ""
    except Exception:
        # Fail fast so callers can fall back to rule/stub paths instead of
        # keeping the UI in a long loading state.
        return ""


def generate_stream(
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.1,
) -> Iterator[str]:
    """Call the LLM with streaming enabled. Yields text chunks as they arrive."""
    client = _get_client()
    resolved_model = model or settings.llm.model
    try:
        response = client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        for chunk in response:
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
    except Exception:
        return
