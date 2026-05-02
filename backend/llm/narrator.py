"""Single Narrator/GM module for the Lite backend."""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from backend.llm.client import LLMAdapter


SYSTEM_PROMPT = """You are the single Narrator/GM for a lightweight text adventure.

Write a short response to the player in the requested output language.
You control only narration. Player state is changed by code through tags.

Use tags when something should enter scene memory or update player state:
[[entity:item|item_id|visible name|available]]
[[entity:npc|npc_id|visible name|available]]
[[entity:place|place_id|visible name|background]]
[[player_change|add_item:item_id]]
[[player_change|add_gold:10]]
[[player_change|remove_item:item_id]]
[[player_change|add_skill:skill_id]]

Rules:
- Return plain text with tags inline.
- Keep it direct and playable.
- Do not output JSON.
- Do not mention backend systems.
- Do not validate player actions in a separate system voice.
- If you add an item, include both an entity tag for it and a player_change tag.
- If you mention an interactable scene thing, include an entity tag for it.
"""


class Narrator:
    """Generate one GM response from the current state and raw player input."""

    def __init__(self, llm_adapter: LLMAdapter) -> None:
        self._llm_adapter = llm_adapter

    def narrate(
        self,
        player_input: str,
        session_state: dict[str, Any],
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        prompt = json.dumps(
            {
                "player_input": player_input,
                "output_language": session_state.get("output_language") or "uk",
                "player_state": session_state.get("player_state", {}),
                "scene_pool": session_state.get("scene_pool", []),
                "recent_messages": session_state.get("recent_messages", [])[-6:],
            },
            ensure_ascii=False,
            indent=2,
        )

        if on_token is not None:
            chunks: list[str] = []
            for chunk in self._llm_adapter.stream_text(SYSTEM_PROMPT, prompt):
                chunks.append(chunk)
                on_token(chunk)
            text = "".join(chunks).strip()
        else:
            response = self._llm_adapter.generate_text(SYSTEM_PROMPT, prompt)
            text = str(response.get("text", "")).strip()

        if text:
            return text
        return self._fallback(player_input)

    def _fallback(self, player_input: str) -> str:
        return (
            "Ти робиш крок уперед і уважно зчитуєш ситуацію навколо. "
            "Світ чекає на твій наступний рух."
        )
