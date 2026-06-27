"""Communication layer for Ollama."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Protocol, TypedDict

import requests

from backend.config import Settings


logger = logging.getLogger(__name__)
OLLAMA_METADATA_KEYS = {
    "done",
    "done_reason",
    "total_duration",
    "load_duration",
    "prompt_eval_count",
    "prompt_eval_duration",
    "eval_count",
    "eval_duration",
}


class LLMGenerateResponse(TypedDict, total=False):
    text: str
    provider: str
    model: str
    used_mock: bool
    error: str


class LLMAdapter(Protocol):
    @property
    def last_diagnostics(self) -> dict[str, object]:
        """Return diagnostics from the most recent generation call."""

    def generate_text(self, system_prompt: str, user_prompt: str) -> LLMGenerateResponse:
        """Generate text using the configured model backend."""

    def stream_text(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        """Stream generated text chunks."""


class OllamaLLMClient:
    """Small Ollama client with an empty-response fallback for local development."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._skip_until = 0.0
        self._last_diagnostics: dict[str, object] = {}

    @property
    def last_diagnostics(self) -> dict[str, object]:
        return dict(self._last_diagnostics)

    def generate_text(self, system_prompt: str, user_prompt: str) -> LLMGenerateResponse:
        self._reset_diagnostics(stream=False)
        if self._settings.allow_mock_fallback and time.monotonic() < self._skip_until:
            return self._build_fallback_response("Skipping request after recent Ollama failure.")

        try:
            payload = self._build_payload(system_prompt, user_prompt, stream=False)
            response = requests.post(
                self._settings.llm_url,
                json=payload,
                timeout=self._settings.llm_timeout_seconds,
            )
            response.raise_for_status()
            response_data = response.json()
        except (requests.RequestException, ValueError) as exc:
            self._skip_until = time.monotonic() + 10
            self._last_diagnostics["stream_error"] = str(exc)
            logger.warning("Ollama request failed: %s", exc)
            return self._build_fallback_response(str(exc))

        self._capture_final_metadata(response_data)
        generated_text = self._extract_response_text(response_data)
        if generated_text is None:
            self._skip_until = time.monotonic() + 10
            return self._build_fallback_response("Ollama returned an empty or invalid response.")

        self._skip_until = 0.0
        return {
            "text": generated_text,
            "provider": "ollama",
            "model": self._settings.model,
            "used_mock": False,
        }

    def stream_text(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        self._reset_diagnostics(stream=True)
        if self._settings.allow_mock_fallback and time.monotonic() < self._skip_until:
            return

        try:
            payload = self._build_payload(system_prompt, user_prompt, stream=True)
            with requests.post(
                self._settings.llm_url,
                json=payload,
                timeout=self._settings.llm_timeout_seconds,
                stream=True,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        response_data = json.loads(line)
                    except ValueError:
                        logger.warning("Could not parse Ollama stream line: %s", line)
                        continue
                    chunk = response_data.get("response", "")
                    if isinstance(chunk, str) and chunk:
                        yield chunk
                    if response_data.get("done"):
                        self._capture_final_metadata(response_data)
                        break
        except requests.RequestException as exc:
            self._skip_until = time.monotonic() + 10
            self._last_diagnostics["stream_error"] = str(exc)
            logger.warning("Ollama stream failed: %s", exc)

    def _build_payload(self, system_prompt: str, user_prompt: str, stream: bool) -> dict[str, object]:
        return {
            "model": self._settings.model,
            "prompt": user_prompt,
            "system": system_prompt,
            "stream": stream,
            "options": self._ollama_options(),
        }

    def _ollama_options(self) -> dict[str, object]:
        return {
            "num_predict": self._settings.ollama_num_predict,
            "num_ctx": self._settings.ollama_num_ctx,
            "temperature": self._settings.ollama_temperature,
        }

    def _reset_diagnostics(self, stream: bool) -> None:
        self._last_diagnostics = {
            "provider": "ollama",
            "model": self._settings.model,
            "stream": stream,
            "options": self._ollama_options(),
            "done": None,
            "done_reason": None,
            "stream_error": None,
        }

    def _capture_final_metadata(self, response_data: object) -> None:
        if not isinstance(response_data, dict):
            return
        for key in OLLAMA_METADATA_KEYS:
            if key in response_data:
                self._last_diagnostics[key] = response_data[key]
        if isinstance(response_data.get("model"), str):
            self._last_diagnostics["model"] = response_data["model"]

    def _extract_response_text(self, response_data: object) -> str | None:
        if not isinstance(response_data, dict):
            return None
        generated_text = response_data.get("response")
        if not isinstance(generated_text, str):
            return None
        cleaned_text = generated_text.strip()
        return cleaned_text or None

    def _build_fallback_response(self, error_text: str) -> LLMGenerateResponse:
        return {
            "text": "",
            "provider": "ollama",
            "model": self._settings.model,
            "used_mock": self._settings.allow_mock_fallback,
            "error": error_text,
        }
