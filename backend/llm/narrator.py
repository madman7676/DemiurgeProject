"""Single Narrator/GM module for the Lite backend."""

from __future__ import annotations

from collections.abc import Callable
import json
import logging
from pathlib import Path
from typing import Any

from backend.llm.client import LLMAdapter


PROMPT_PATH = Path(__file__).with_name("narrator_prompt.txt")
logger = logging.getLogger(__name__)


class Narrator:
    """Generate one GM response from the current state and raw player input."""

    def __init__(self, llm_adapter: LLMAdapter) -> None:
        self._llm_adapter = llm_adapter
        self._system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
        self.last_diagnostics: dict[str, Any] = {}

    def narrate(
        self,
        player_input: str,
        session_state: dict[str, Any],
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        prompt = json.dumps(
            {
                "current_location": session_state.get("scene", {}).get("location", {}),
                "current_scene_entities": session_state.get("scene", {}).get("entities", []),
                "player_inventory": session_state.get("player", {}).get("inventory", []),
                "player_currencies": session_state.get("player", {}).get("currencies", []),
                "player_skills": session_state.get("player", {}).get("skills", []),
                "recent_history": session_state.get("history", [])[-8:],
                "player_input": player_input,
                "output_language": session_state.get("output_language") or "uk",
            },
            ensure_ascii=False,
            indent=2,
        )

        if on_token is not None:
            chunks: list[str] = []
            for chunk in self._llm_adapter.stream_text(self._system_prompt, prompt):
                chunks.append(chunk)
                on_token(chunk)
            text = "".join(chunks).strip()
        else:
            response = self._llm_adapter.generate_text(self._system_prompt, prompt)
            text = str(response.get("text", "")).strip()

        if text:
            self.last_diagnostics = self._build_diagnostics(text)
            self._log_diagnostics()
            return text
        fallback_text = self._fallback(player_input)
        self.last_diagnostics = self._build_diagnostics(fallback_text)
        self._log_diagnostics()
        return fallback_text

    def _build_diagnostics(self, response_text: str) -> dict[str, Any]:
        diagnostics = dict(getattr(self._llm_adapter, "last_diagnostics", {}) or {})
        diagnostics.update(_tag_diagnostics(response_text))
        diagnostics["raw_response_length"] = len(response_text)
        return diagnostics

    def _log_diagnostics(self) -> None:
        diagnostics = self.last_diagnostics
        options = diagnostics.get("options", {})
        if not isinstance(options, dict):
            options = {}
        logger.info(
            "llm_request model=%s num_predict=%s num_ctx=%s response_length=%s done_reason=%s "
            "unclosed_tag=%s stream_error=%s",
            diagnostics.get("model"),
            options.get("num_predict"),
            options.get("num_ctx"),
            diagnostics.get("raw_response_length"),
            diagnostics.get("done_reason"),
            diagnostics.get("has_unclosed_tag"),
            diagnostics.get("stream_error"),
        )

    def _fallback(self, player_input: str) -> str:
        return (
            "Ти робиш крок уперед і уважно зчитуєш ситуацію навколо. "
            "Світ чекає на твій наступний рух."
        )


def _tag_diagnostics(response_text: str) -> dict[str, Any]:
    last_open = response_text.rfind("[[")
    last_close = response_text.rfind("]]")
    has_unclosed_tag = last_open > last_close
    tag_kind = ""

    if has_unclosed_tag:
        tag_body = response_text[last_open + 2 :]
        if tag_body.startswith("entity:"):
            tag_kind = "entity"
        elif tag_body.startswith("player_change|"):
            tag_kind = "player_change"
        elif tag_body.startswith("scene_change|"):
            tag_kind = "scene_change"

    return {
        "has_unclosed_tag": has_unclosed_tag,
        "ends_inside_tag_kind": tag_kind,
        "ends_inside_known_tag": bool(tag_kind),
    }
