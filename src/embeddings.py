"""
Embedding layer — pluggable, multilingual text embeddings.

Default provider is BGE-M3 (BAAI/bge-m3): a multilingual model covering
English, Chinese, and 100+ languages, chosen because the product serves both
English- and Chinese-speaking users (Decision D-011). The provider interface
is pluggable so the embedding backend can be swapped to a hosted API (OpenAI)
or a deterministic fake (for tests) without touching downstream code.

Design notes:
- Models are loaded lazily and held as process-singletons. Importing this
  module never triggers a multi-GB model download.
- Query embeddings are cached in-process (queries repeat across eval runs and
  multi-turn chat). Document embeddings are batched, not cached.
- All providers expose the SAME interface: embed_documents / embed_query /
  dimension. pgvector stores normalized dense vectors and uses cosine distance.
"""

from __future__ import annotations

import hashlib
import struct
from abc import ABC, abstractmethod
from functools import lru_cache

from src.config import settings


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class EmbeddingProvider(ABC):
    """Abstract embedding provider. All backends implement this contract."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimension produced by this provider."""

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of passages/documents."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query."""


# ---------------------------------------------------------------------------
# BGE-M3 (local, multilingual) — default
# ---------------------------------------------------------------------------

class BGEEmbedding(EmbeddingProvider):
    """BAAI/bge-m3 dense embeddings via sentence-transformers.

    bge-m3 produces 1024-dim dense vectors and is normalized for cosine
    similarity. The model is loaded on first use only.
    """

    def __init__(self) -> None:
        self._model = None
        self._dim = settings.embedding.dimension

    def _load(self):
        if self._model is None:
            # Lazy import so module import stays cheap and torch is optional
            # at import time (tests can use the fake provider).
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                settings.embedding.model,
                device=settings.embedding.device,
            )
            # Trust the model's real dimension if it differs from config.
            try:
                self._dim = self._model.get_sentence_embedding_dimension()
            except Exception:
                pass
        return self._model

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vecs = model.encode(
            texts,
            batch_size=settings.embedding.batch_size,
            normalize_embeddings=settings.embedding.normalize,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [v.tolist() for v in vecs]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


# ---------------------------------------------------------------------------
# OpenAI (hosted) — optional
# ---------------------------------------------------------------------------

class OpenAIEmbedding(EmbeddingProvider):
    """Hosted OpenAI embeddings (text-embedding-3-*).

    NOTE: less suited to Chinese than bge-m3; provided as a drop-in alternative
    for English-heavy or no-local-GPU deployments.
    """

    _DIMS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072}

    def __init__(self) -> None:
        self._client = None
        self._model = settings.embedding.openai_model

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=settings.llm.api_key, base_url=settings.llm.base_url
            )
        return self._client

    @property
    def dimension(self) -> int:
        return self._DIMS.get(self._model, settings.embedding.dimension)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = self._get_client().embeddings.create(model=self._model, input=texts)
        return [d.embedding for d in resp.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


# ---------------------------------------------------------------------------
# Fake (deterministic) — for tests / offline CI
# ---------------------------------------------------------------------------

class FakeEmbedding(EmbeddingProvider):
    """Deterministic hash-based embeddings. No model download, no network.

    Produces stable, normalized pseudo-vectors so retrieval wiring can be
    exercised end-to-end in CI without heavyweight model dependencies.
    """

    def __init__(self, dim: int | None = None) -> None:
        self._dim = dim or settings.embedding.dimension

    @property
    def dimension(self) -> int:
        return self._dim

    def _vec(self, text: str) -> list[float]:
        out: list[float] = []
        seed = text.encode("utf-8")
        counter = 0
        while len(out) < self._dim:
            h = hashlib.sha256(seed + struct.pack(">I", counter)).digest()
            for i in range(0, len(h), 4):
                if len(out) >= self._dim:
                    break
                val = struct.unpack(">I", h[i:i + 4])[0] / 0xFFFFFFFF
                out.append(val - 0.5)
            counter += 1
        norm = sum(x * x for x in out) ** 0.5 or 1.0
        return [x / norm for x in out]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


# ---------------------------------------------------------------------------
# Factory + query cache
# ---------------------------------------------------------------------------

_PROVIDER: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    """Return the configured embedding provider (process singleton)."""
    global _PROVIDER
    if _PROVIDER is None:
        provider = settings.embedding.provider.lower()
        if provider == "openai":
            _PROVIDER = OpenAIEmbedding()
        elif provider == "fake":
            _PROVIDER = FakeEmbedding()
        else:
            _PROVIDER = BGEEmbedding()
    return _PROVIDER


def set_embedding_provider(provider: EmbeddingProvider | None) -> None:
    """Override the active provider (used by tests). Pass None to reset."""
    global _PROVIDER
    _PROVIDER = provider
    embed_query.cache_clear()


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed a batch of documents with the active provider."""
    return get_embedding_provider().embed_documents(texts)


@lru_cache(maxsize=2048)
def embed_query(text: str) -> tuple[float, ...]:
    """Embed a single query (cached). Returns a tuple so it is hashable."""
    return tuple(get_embedding_provider().embed_query(text))


def embedding_dimension() -> int:
    return get_embedding_provider().dimension
