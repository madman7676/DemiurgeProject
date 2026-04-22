"""Communication layer for the local LLM.

Other backend modules should call into this module instead of talking to the model directly.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

import requests

from backend.config import Settings
from backend.modules.llm_connector.schemas.llm_contracts import LLMGenerateResponse


logger = logging.getLogger(__name__)


class LLMAdapter(Protocol):
    """Small interface used by gameplay services that depend on text generation."""

    def generate_text(self, system_prompt: str, user_prompt: str) -> LLMGenerateResponse:
        """Generate text using the configured model backend."""


class OllamaLLMClient:
    """Ollama adapter with a graceful mock fallback for local development."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._skip_until = 0.0

    def generate_text(self, system_prompt: str, user_prompt: str) -> LLMGenerateResponse:
        """Send a non-streaming prompt to Ollama and return the text result."""

        if self._settings.allow_mock_fallback and time.monotonic() < self._skip_until:
            logger.info("Skipping Ollama call because the adapter is in fallback cooldown.")
            return self._build_fallback_response("Skipping request after recent Ollama failure.")

        logger.info(
            "Calling Ollama model '%s' at %s",
            self._settings.model,
            self._settings.llm_url,
        )

        try:
            response = requests.post(
                self._settings.llm_url,
                json=self._build_payload(system_prompt, user_prompt),
                timeout=self._settings.llm_timeout_seconds,
            )
            response.raise_for_status()
            response_data = response.json()
        except (requests.RequestException, ValueError) as exc:
            self._skip_until = time.monotonic() + 10
            logger.warning("Ollama request failed: %s", exc)
            return self._build_fallback_response(str(exc))

        generated_text = self._extract_response_text(response_data)
        if generated_text is None:
            self._skip_until = time.monotonic() + 10
            logger.warning("Ollama returned an empty or invalid response payload.")
            return self._build_fallback_response("Ollama returned an empty or invalid response.")

        self._skip_until = 0.0
        logger.info("Ollama response received successfully.")
        return {
            "text": generated_text,
            "provider": "ollama",
            "model": self._settings.model,
            "used_mock": False,
        }

    def _build_payload(self, system_prompt: str, user_prompt: str) -> dict[str, object]:
        """Build the minimal non-streaming Ollama request body."""

        return {
            "model": self._settings.model,
            "prompt": user_prompt,
            "system": system_prompt,
            "stream": False,
        }

    def _extract_response_text(self, response_data: object) -> str | None:
        """Extract generated text from the Ollama response payload."""

        if not isinstance(response_data, dict):
            return None

        generated_text = response_data.get("response")
        if not isinstance(generated_text, str):
            return None

        cleaned_text = generated_text.strip()
        return cleaned_text or None

    def _build_fallback_response(self, error_text: str) -> LLMGenerateResponse:
        """Return an empty mock response so callers can use deterministic fallbacks."""

        return {
            "text": "",
            "provider": "ollama",
            "model": self._settings.model,
            "used_mock": self._settings.allow_mock_fallback,
            "error": error_text,
        }
