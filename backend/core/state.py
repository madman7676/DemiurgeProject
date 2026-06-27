"""In-memory GameState for the tag-driven Lite backend."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


HISTORY_LIMIT = 20
DEFAULT_ICON = {
    "item": "•",
    "npc": "☻",
    "enemy": "!",
    "place": "⌂",
    "skill": "*",
    "currency": "$",
}


def create_initial_game_state() -> dict[str, Any]:
    return {
        "scene": {
            "location": {
                "id": "stonemarket",
                "name": "Crowded market crossroads",
                "icon": "⌂",
            },
            "entities": [],
            "last_response": "",
        },
        "player": {
            "inventory": [
                {"id": "old_compass", "name": "Old Compass", "icon": "◌"},
                {"id": "travel_cloak", "name": "Travel Cloak", "icon": "▧"},
            ],
            "currencies": [
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
            "parsed_tags": {"entities": [], "player_changes": [], "scene_changes": []},
            "applied_changes": [],
            "malformed_or_skipped_tags": [],
            "scene_entities_skipped_due_to_ownership": [],
        },
        "latest_change_summary": [],
        "turn_count": 0,
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
    """Accept client snapshots while keeping the Lite shape intact."""

    normalized = deepcopy(state) if isinstance(state, dict) else {}
    normalized.setdefault("scene", {})
    normalized["scene"].setdefault("location", {"id": "unknown", "name": "unknown", "icon": "⌂"})
    normalized["scene"].setdefault("entities", [])
    normalized["scene"].setdefault("last_response", "")
    normalized.setdefault("player", {})
    normalized["player"].setdefault("inventory", [])
    normalized["player"].setdefault("currencies", [])
    normalized["player"].setdefault("skills", [])
    normalized.setdefault("history", [])
    normalized.setdefault("debug", {})
    normalized["debug"].setdefault("raw_llm_response", "")
    normalized["debug"].setdefault("narrator_response_for_ui", "")
    normalized["debug"].setdefault("llm_diagnostics", {})
    normalized["debug"].setdefault("parsed_tags", {"entities": [], "player_changes": [], "scene_changes": []})
    normalized["debug"]["parsed_tags"].setdefault("scene_changes", [])
    normalized["debug"].setdefault("applied_changes", [])
    normalized["debug"].setdefault("malformed_or_skipped_tags", [])
    normalized["debug"].setdefault("scene_entities_skipped_due_to_ownership", [])
    normalized.setdefault("latest_change_summary", [])
    normalized.setdefault("turn_count", 0)
    normalized.setdefault("output_language", "")
    return normalized


def build_visible_state(game_state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(game_state)


def append_history_turn(
    game_state: dict[str, Any],
    user_input: str,
    narrator_response_for_ui: str,
    narrator_response_clean: str,
    parsed_entities: list[dict[str, Any]],
    applied_changes: list[dict[str, Any]],
) -> None:
    history = game_state.setdefault("history", [])
    history.append(
        {
            "user_input": user_input,
            "narrator_response_for_ui": narrator_response_for_ui,
            "narrator_response_clean": narrator_response_clean,
            "parsed_entities": deepcopy(parsed_entities),
            "applied_changes": deepcopy(applied_changes),
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
        if index == len(history) - 1 and game_state.get("latest_change_summary"):
            assistant_message["change_summary"] = deepcopy(game_state["latest_change_summary"])
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


def entity_to_inventory_item(entity: dict[str, Any], fallback_id: str) -> dict[str, str]:
    return {
        "id": str(entity.get("id") or fallback_id),
        "name": str(entity.get("name") or fallback_id),
        "icon": str(entity.get("icon") or DEFAULT_ICON["item"]),
    }


def entity_to_skill(entity: dict[str, Any], fallback_id: str) -> dict[str, str]:
    return {
        "id": str(entity.get("id") or fallback_id),
        "name": str(entity.get("name") or fallback_id),
        "icon": str(entity.get("icon") or DEFAULT_ICON["skill"]),
    }


def entity_to_currency(entity: dict[str, Any], amount: int = 0) -> dict[str, Any]:
    return {
        "id": str(entity["id"]),
        "name": str(entity.get("name") or entity["id"]),
        "icon": str(entity.get("icon") or DEFAULT_ICON["currency"]),
        "amount": amount,
    }


def entity_to_location(entity: dict[str, Any], fallback_id: str) -> dict[str, str]:
    return {
        "id": str(entity.get("id") or fallback_id),
        "name": str(entity.get("name") or fallback_id),
        "icon": str(entity.get("icon") or DEFAULT_ICON["place"]),
    }
