"""Backend runtime configuration for the Hyperlite backend."""

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
    ollama_num_predict: int
    ollama_num_ctx: int
    ollama_temperature: float
    allow_mock_fallback: bool


def load_settings() -> Settings:
    """Load settings from environment variables with local-dev defaults."""

    return Settings(
        model=os.getenv("OLLAMA_MODEL", "gemma3:12b"),
        llm_url=os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate"),
        host=os.getenv("BACKEND_HOST", "127.0.0.1"),
        port=int(os.getenv("BACKEND_PORT", "8000")),
        llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "240")),
        ollama_num_predict=int(os.getenv("OLLAMA_NUM_PREDICT", "1024")),
        ollama_num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "8192")),
        ollama_temperature=float(os.getenv("OLLAMA_TEMPERATURE", "0.7")),
        allow_mock_fallback=os.getenv("ALLOW_MOCK_LLM", "true").lower() != "false",
    )
