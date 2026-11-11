"""Settings from the environment. Every model choice is configuration: change it without touching code."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _chain(name: str, default: str) -> tuple[str, ...]:
    return tuple(m.strip() for m in os.environ.get(name, default).split(",") if m.strip())


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    # Read-only login role created with `python -m explainer_data create-reader` — never the owner.
    database_url: str = field(default_factory=lambda: os.environ.get("READER_DATABASE_URL", ""))
    groq_api_key: str = field(default_factory=lambda: os.environ.get("GROQ_API_KEY", ""))
    groq_base_url: str = field(
        default_factory=lambda: os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    )

    # Fallback chains, first model first.
    router_models: tuple[str, ...] = field(
        default_factory=lambda: _chain("ROUTER_MODELS", "openai/gpt-oss-20b,openai/gpt-oss-120b")
    )
    sql_models: tuple[str, ...] = field(
        default_factory=lambda: _chain("SQL_MODELS", "openai/gpt-oss-120b,openai/gpt-oss-20b")
    )
    answer_models: tuple[str, ...] = field(
        default_factory=lambda: _chain("ANSWER_MODELS", "openai/gpt-oss-120b,openai/gpt-oss-20b")
    )
    router_timeout_s: float = field(default_factory=lambda: _float("ROUTER_TIMEOUT_S", 3))
    model_timeout_s: float = field(default_factory=lambda: _float("MODEL_TIMEOUT_S", 8))

    embedding_model: str = field(
        default_factory=lambda: os.environ.get(
            "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
    )
    rag_top_k: int = field(default_factory=lambda: _int("RAG_TOP_K", 5))
    sql_row_limit: int = field(default_factory=lambda: _int("SQL_ROW_LIMIT", 200))

    # Protections. One Fly machine keeps these counters in memory; more machines would need a shared store.
    qa_enabled: bool = field(default_factory=lambda: os.environ.get("QA_ENABLED", "true").lower() == "true")
    per_ip_per_minute: int = field(default_factory=lambda: _int("PER_IP_PER_MINUTE", 5))
    per_ip_per_day: int = field(default_factory=lambda: _int("PER_IP_PER_DAY", 30))
    daily_quota: int = field(default_factory=lambda: _int("DAILY_QUOTA", 300))
    max_question_chars: int = field(default_factory=lambda: _int("MAX_QUESTION_CHARS", 400))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: _chain("CORS_ORIGINS", "http://localhost:5173"))
