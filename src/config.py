"""
Central application configuration.

Single source of truth for all runtime settings. Every module reads config
from here instead of calling os.environ directly, so behaviour is consistent
across the web server, CLI, ingestion jobs, and eval harness.

Backwards compatible with the legacy env names (LLM_ENDPOINT, LLM_API_KEY,
LLM_MODEL, LLM_TIMEOUT_SECONDS) used by the MVP.

Usage:
    from src.config import settings
    settings.llm.model
    settings.embedding.model
    settings.database.url
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env into os.environ FIRST, so that nested BaseSettings groups (which
# read from the process environment by prefix) pick up .env values too. Without
# this, only the top-level AppSettings would see .env and nested groups like
# LLMSettings would silently fall back to their code defaults.
load_dotenv(PROJECT_ROOT / ".env")
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SOURCES_DIR = DATA_DIR / "sources"
PROCESSED_CHUNKS_FILE = PROCESSED_DIR / "chunks.jsonl"
URL_REGISTRY_FILE = SOURCES_DIR / "url_registry.json"


# ---------------------------------------------------------------------------
# Sub-config groups
# ---------------------------------------------------------------------------

class LLMSettings(BaseSettings):
    """LLM generation provider settings (provider-agnostic, OpenAI-compatible)."""
    model_config = SettingsConfigDict(env_prefix="LLM_", extra="ignore")

    endpoint: str = Field(default="https://ark.cn-beijing.volces.com/api/v3/chat/completions")
    api_key: str = Field(default="")
    model: str = Field(default="deepseek-v4-flash-260425")
    timeout_seconds: float = Field(default=45.0)
    # Effective context window of the generation model (tokens). Used by the
    # context-budget manager in agent_module to size retrieved evidence.
    # deepseek-v4-flash supports a large window; keep conservative and override
    # via LLM_CONTEXT_WINDOW_TOKENS if you want to use more of it.
    context_window_tokens: int = Field(default=65536)
    max_output_tokens: int = Field(default=2048)
    temperature: float = Field(default=0.1)

    @property
    def base_url(self) -> str:
        """OpenAI SDK base_url (strip the chat/completions suffix)."""
        return self.endpoint.removesuffix("/chat/completions")


class EmbeddingSettings(BaseSettings):
    """Embedding model settings.

    Default is the multilingual bge-m3 model (EN + ZH + 100+ languages),
    chosen because the product serves English- and Chinese-speaking users
    (D-011). Pluggable: set provider=openai to use a hosted embedding API.
    """
    model_config = SettingsConfigDict(env_prefix="EMBEDDING_", extra="ignore")

    provider: str = Field(default="bge")  # "bge" (local, multilingual) | "openai"
    model: str = Field(default="BAAI/bge-m3")
    dimension: int = Field(default=1024)
    device: str = Field(default="cpu")  # "cpu" | "cuda" | "mps"
    batch_size: int = Field(default=32)
    normalize: bool = Field(default=True)
    # OpenAI embedding fallback (only used when provider=openai)
    openai_model: str = Field(default="text-embedding-3-large")


class RerankerSettings(BaseSettings):
    """Cross-encoder reranker settings (post-hybrid stage)."""
    model_config = SettingsConfigDict(env_prefix="RERANKER_", extra="ignore")

    enabled: bool = Field(default=True)
    model: str = Field(default="BAAI/bge-reranker-v2-m3")  # multilingual cross-encoder
    device: str = Field(default="cpu")
    batch_size: int = Field(default=16)


class DatabaseSettings(BaseSettings):
    """Postgres + pgvector connection settings."""
    model_config = SettingsConfigDict(env_prefix="DB_", extra="ignore")

    host: str = Field(default="localhost")
    port: int = Field(default=5432)
    name: str = Field(default="rag")
    user: str = Field(default="rag")
    password: str = Field(default="rag")
    # Override everything with a single DSN if provided.
    url_override: str = Field(default="")
    pool_min: int = Field(default=1)
    pool_max: int = Field(default=8)

    @property
    def url(self) -> str:
        if self.url_override:
            return self.url_override
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


class RetrievalSettings(BaseSettings):
    """Hybrid retrieval + fusion settings (supersedes hardcoded D-004 constants)."""
    model_config = SettingsConfigDict(env_prefix="RETRIEVAL_", extra="ignore")

    top_k_initial: int = Field(default=20)
    top_k_final: int = Field(default=5)
    # Reciprocal Rank Fusion constant for combining dense + keyword rankings.
    rrf_k: int = Field(default=60)
    # Legacy linear-blend weights (kept for fallback hybrid path).
    bm25_weight: float = Field(default=0.6)
    vector_weight: float = Field(default=0.4)
    use_reranker: bool = Field(default=True)
    # Backend selection: "pgvector" (production) | "chroma" (legacy fallback)
    backend: str = Field(default="pgvector")


class AppSettings(BaseSettings):
    """Top-level application settings."""
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = Field(default="development")  # development | staging | production
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)
    web_host: str = Field(default="0.0.0.0")
    web_port: int = Field(default=5050)

    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    reranker: RerankerSettings = Field(default_factory=RerankerSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Cached singleton accessor."""
    return AppSettings()


# Module-level singleton for convenient imports.
settings = get_settings()
