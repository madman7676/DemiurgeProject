"""Communication layer for the local LLM.

Other backend modules should call into this module instead of talking to the model directly.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Protocol
from urllib import error, request

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

        payload = {
            "model": self._settings.model,
            "prompt": user_prompt,
            "system": system_prompt,
            "stream": False,
        }
        encoded_payload = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self._settings.llm_url,
            data=encoded_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        logger.info(
            "Calling Ollama model '%s' at %s",
            self._settings.model,
            self._settings.llm_url,
        )

        try:
            with request.urlopen(
                http_request,
                timeout=self._settings.llm_timeout_seconds,
            ) as response:
                raw_response = response.read().decode("utf-8")
                response_data = json.loads(raw_response)
        except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            self._skip_until = time.monotonic() + 10
            logger.warning("Ollama request failed: %s", exc)
            return self._build_fallback_response(str(exc))

        if not isinstance(response_data, dict):
            self._skip_until = time.monotonic() + 10
            logger.warning("Ollama returned a non-object response.")
            return self._build_fallback_response("Ollama returned a non-object response.")

        generated_text = response_data.get("response", "")
        if not isinstance(generated_text, str) or not generated_text.strip():
            logger.warning("Ollama returned an empty or invalid response payload.")
            return self._build_fallback_response("Ollama returned an empty or invalid response.")

        self._skip_until = 0.0
        logger.info("Ollama response received successfully.")
        return {
            "text": generated_text.strip(),
            "provider": "ollama",
            "model": self._settings.model,
            "used_mock": False,
        }

    def _build_fallback_response(self, error_text: str) -> LLMGenerateResponse:
        """Return an empty mock response so callers can use deterministic fallbacks."""

        return {
            "text": "",
            "provider": "ollama",
            "model": self._settings.model,
            "used_mock": self._settings.allow_mock_fallback,
            "error": error_text,
        }
