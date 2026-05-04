"""Single Narrator/GM module for the Lite backend."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

from backend.llm.client import LLMAdapter


PROMPT_PATH = Path(__file__).with_name("narrator_prompt.txt")


class Narrator:
    """Generate one GM response from the current state and raw player input."""

    def __init__(self, llm_adapter: LLMAdapter) -> None:
        self._llm_adapter = llm_adapter
        self._system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

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
            return text
        return self._fallback(player_input)

    def _fallback(self, player_input: str) -> str:
        return (
            "Ти робиш крок уперед і уважно зчитуєш ситуацію навколо. "
            "Світ чекає на твій наступний рух."
        )
