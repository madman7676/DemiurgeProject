"""In-memory GameState for the Hyperlite backend."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


HISTORY_LIMIT = 20


def create_initial_game_state() -> dict[str, Any]:
    return {
        "player": {
            "inventory": [
                {"id": "old_compass", "name": "Old Compass", "icon": "◌", "quantity": 1},
                {"id": "travel_cloak", "name": "Travel Cloak", "icon": "▧", "quantity": 1},
            ],
            "resources": [
                {"id": "coin", "name": "Coin", "icon": "$", "amount": 7},
            ],
            "skills": [
                {"id": "negotiation", "name": "Negotiation", "icon": "◇"},
                {"id": "awareness", "name": "Awareness", "icon": "◈"},
                {"id": "save_spot", "name": "Save Spot", "icon": "*"},
            ],
        },
        "history": [],
        "debug": {
            "raw_llm_response": "",
            "narrator_response_for_ui": "",
            "llm_diagnostics": {},
            "parsed_tags": {"player_changes": []},
            "applied_changes": [],
            "malformed_or_skipped_tags": [],
            "warnings": [],
        },
        "output_language": "",
    }


class InMemorySessionStore:
    """Single GameState store used by the local prototype."""

    def __init__(self) -> None:
        self._game_state = create_initial_game_state()

    def get_session(self) -> dict[str, Any]:
        return self._game_state

    def replace_session(self, state: dict[str, Any]) -> None:
        self._game_state = normalize_game_state(state)


def normalize_game_state(state: dict[str, Any]) -> dict[str, Any]:
    """Accept client snapshots while keeping the Hyperlite shape intact."""

    source = deepcopy(state) if isinstance(state, dict) else {}
    source_player = source.get("player", {}) if isinstance(source.get("player", {}), dict) else {}
    normalized = {
        "player": {
            "inventory": source_player.get("inventory", [])
            if isinstance(source_player.get("inventory", []), list)
            else [],
            "resources": source_player.get("resources", [])
            if isinstance(source_player.get("resources", []), list)
            else [],
            "skills": source_player.get("skills", [])
            if isinstance(source_player.get("skills", []), list)
            else [],
        },
        "history": source.get("history", []) if isinstance(source.get("history", []), list) else [],
        "debug": source.get("debug", {}) if isinstance(source.get("debug", {}), dict) else {},
        "output_language": str(source.get("output_language", "")),
    }
    normalized["debug"].setdefault("raw_llm_response", "")
    normalized["debug"].setdefault("narrator_response_for_ui", "")
    normalized["debug"].setdefault("llm_diagnostics", {})
    normalized["debug"].setdefault("parsed_tags", {"player_changes": []})
    normalized["debug"].setdefault("applied_changes", [])
    normalized["debug"].setdefault("malformed_or_skipped_tags", [])
    normalized["debug"].setdefault("warnings", [])
    normalized.setdefault("output_language", "")
    return normalized


def build_visible_state(game_state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(game_state)


def append_history_turn(
    game_state: dict[str, Any],
    user_input: str,
    narrator_response_for_ui: str,
    narrator_response_clean: str,
    applied_changes: list[dict[str, Any]],
    change_summary: list[dict[str, str]],
) -> None:
    history = game_state.setdefault("history", [])
    history.append(
        {
            "user_input": user_input,
            "narrator_response_for_ui": narrator_response_for_ui,
            "narrator_response_clean": narrator_response_clean,
            "applied_changes": deepcopy(applied_changes),
            "change_summary": deepcopy(change_summary),
        }
    )
    del history[:-HISTORY_LIMIT]


def build_messages(game_state: dict[str, Any]) -> list[dict[str, str]]:
    messages: list[dict[str, Any]] = []
    history = game_state.get("history", [])
    for index, turn in enumerate(history):
        messages.append({"role": "player", "text": str(turn.get("user_input", ""))})
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "text": str(
                turn.get("narrator_response_for_ui")
                or turn.get("narrator_response_clean", "")
            ),
        }
        if index == len(history) - 1 and turn.get("change_summary"):
            assistant_message["change_summary"] = deepcopy(turn["change_summary"])
        messages.append(assistant_message)
    return messages


def detect_output_language(raw_input: str, fallback: str = "uk") -> str:
    text = raw_input.strip()
    if not text:
        return fallback
    if any(character in text.casefold() for character in ["і", "ї", "є", "ґ"]):
        return "uk"
    cyrillic_count = sum(1 for character in text if "А" <= character <= "я")
    latin_count = sum(1 for character in text if character.isascii() and character.isalpha())
    if cyrillic_count > latin_count:
        return "uk"
    if latin_count > cyrillic_count:
        return "en"
    return fallback
