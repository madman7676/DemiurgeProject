"""Backend runtime configuration for the minimal exploration pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the local backend and Ollama connection."""

    model: str
    llm_url: str
    host: str
    port: int
    llm_timeout_seconds: int
    allow_mock_fallback: bool


def load_settings() -> Settings:
    """Load settings from environment variables with local-dev defaults."""

    return Settings(
        model=os.getenv("MODEL", "gemma3:12b"),
        llm_url=os.getenv("LLM_URL", "http://localhost:11434/api/generate"),
        host=os.getenv("BACKEND_HOST", "127.0.0.1"),
        port=int(os.getenv("BACKEND_PORT", "8000")),
        llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
        allow_mock_fallback=os.getenv("ALLOW_MOCK_LLM", "true").lower() != "false",
    )
