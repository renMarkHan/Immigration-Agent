"""
LLM client — thin wrapper around the OpenAI-compatible endpoint.

Owner: Yuhan Ren (Framework Owner)
All modules call generate() from here; never instantiate the client directly.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ["LLM_API_KEY"]
        base_url = os.environ["LLM_ENDPOINT"].removesuffix("/chat/completions")
        _client = OpenAI(api_key=api_key, base_url=base_url)
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
    resolved_model = model or os.environ.get("LLM_MODEL", "qwen3-30b-a3b-fp8")
    resolved_timeout = timeout_seconds
    if resolved_timeout is None:
        try:
            resolved_timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "45"))
        except Exception:
            resolved_timeout = 45.0

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
