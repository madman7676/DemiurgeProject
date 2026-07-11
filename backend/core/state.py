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
            "resources": [],
            "currencies": [
                {"id": "coin", "name": "Coin", "icon": "$", "amount": 7},
            ],
            "skills": [
                {"id": "negotiation", "name": "Negotiation", "icon": "◇", "level": 1, "progress": 0},
                {"id": "awareness", "name": "Awareness", "icon": "◈", "level": 1, "progress": 0},
                {"id": "save_spot", "name": "Save Spot", "icon": "*", "level": 1, "progress": 0},
            ],
        },
        "history": [],
        "debug": {
            "raw_llm_response": "",
            "narrator_response_for_ui": "",
            "llm_diagnostics": {},
            "parsed_tags": {"player_changes": []},
            "applied_changes": [],
            "player_inventory": [],
            "player_resources": [],
            "player_currencies": [],
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
            "inventory": _normalize_stacks(source_player.get("inventory", []), "quantity", keep_zero=False),
            "resources": _normalize_stacks(source_player.get("resources", []), "amount", keep_zero=False),
            "currencies": _normalize_stacks(source_player.get("currencies", []), "amount", keep_zero=True),
            "skills": _normalize_skills(source_player.get("skills", [])),
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
    normalized["debug"].setdefault("player_inventory", [])
    normalized["debug"].setdefault("player_resources", [])
    normalized["debug"].setdefault("player_currencies", [])
    normalized["debug"].setdefault("malformed_or_skipped_tags", [])
    normalized["debug"].setdefault("warnings", [])
    normalized.setdefault("output_language", "")
    return normalized


def _normalize_stacks(value: object, amount_key: str, keep_zero: bool) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for stack in value:
        if not isinstance(stack, dict):
            continue
        stack_id = str(stack.get("id", "")).strip()
        if not stack_id:
            continue
        amount = _to_non_negative_int(stack.get(amount_key, 0))
        if amount <= 0 and not keep_zero:
            continue
        normalized.append(
            {
                "id": stack_id,
                "name": str(stack.get("name") or stack_id),
                "icon": str(stack.get("icon") or "•"),
                amount_key: amount,
            }
        )
    return normalized


def _normalize_skills(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for skill in value:
        if not isinstance(skill, dict):
            continue
        skill_id = str(skill.get("id", "")).strip()
        if not skill_id:
            continue
        normalized_skill: dict[str, Any] = {
            "id": skill_id,
            "name": str(skill.get("name") or skill_id),
            "icon": str(skill.get("icon") or "*"),
            "level": _to_non_negative_int(skill.get("level", 0)),
            "progress": min(99, _to_non_negative_int(skill.get("progress", 0))),
        }
        description = skill.get("description")
        if description:
            normalized_skill["description"] = str(description)
        normalized.append(normalized_skill)
    return normalized


def _to_non_negative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def build_visible_state(game_state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(game_state)


def append_history_turn(
    game_state: dict[str, Any],
    user_input: str,
    narrator_response_for_ui: str,
    narrator_response_clean: str,
    applied_changes: list[dict[str, Any]],
) -> None:
    history = game_state.setdefault("history", [])
    history.append(
        {
            "user_input": user_input,
            "narrator_response_for_ui": narrator_response_for_ui,
            "narrator_response_clean": narrator_response_clean,
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
