"""Small in-memory state store for the Lite backend."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4


def create_initial_player_state() -> dict[str, Any]:
    """Return the default player state for local development."""

    return {
        "identity": {
            "player_id": "player_dynamic_001",
            "name": "Riven Ash",
        },
        "race": "Human",
        "player_class": "Wanderer",
        "background": "A former caravan scout trying to rebuild a life after losing their trade route.",
        "stats": [
            {"stat_id": "resolve", "name": "Resolve", "value": 4},
            {"stat_id": "agility", "name": "Agility", "value": 3},
        ],
        "skills": [
            {
                "skill_id": "negotiation",
                "name": "Negotiation",
                "level": 1,
                "aliases": ["haggle", "bargain"],
            },
            {
                "skill_id": "awareness",
                "name": "Awareness",
                "level": 2,
                "aliases": ["notice", "observe"],
            },
            {
                "skill_id": "save_spot",
                "name": "Save Spot",
                "level": 1,
                "type": "active",
                "aliases": ["safe blink", "escape point", "secure step"],
                "description": "Instantly teleports the player to the nearest safe location within range.",
            },
        ],
        "inventory": [
            {
                "item_id": "old_compass",
                "name": "Old Compass",
                "quantity": 1,
                "aliases": ["compass"],
            },
            {
                "item_id": "travel_cloak",
                "name": "Travel Cloak",
                "quantity": 1,
                "aliases": ["cloak"],
            },
        ],
        "equipped_items": [
            {
                "item_id": "travel_cloak",
                "name": "Travel Cloak",
                "quantity": 1,
                "aliases": ["cloak"],
            }
        ],
        "held_items": [
            {
                "item_id": "old_compass",
                "name": "Old Compass",
                "quantity": 1,
                "aliases": ["compass"],
            }
        ],
        "currencies": [
            {
                "currency_id": "coin",
                "name": "Coin",
                "amount": 7,
                "aliases": ["coins", "gold"],
            }
        ],
        "status_effects": [],
        "current_location": {
            "region_id": "stonemarket",
            "detail": "Crowded market crossroads",
        },
        "party_links": [],
    }


def create_initial_session_state() -> dict[str, Any]:
    player_state = create_initial_player_state()
    return {
        "session_id": f"session-{uuid4()}",
        "mode": "exploration",
        "player_state": player_state,
        "current_time": {"year": 1, "month": 1, "day": 1, "hour": 8, "minute": 0},
        "scene_pool": [],
        "recent_messages": [],
        "decision_history": [],
        "output_language": "",
        "turn_count": 0,
    }


class InMemorySessionStore:
    """Single-session store used by the local prototype."""

    def __init__(self) -> None:
        self._session_state = create_initial_session_state()

    def get_session(self) -> dict[str, Any]:
        return self._session_state

    def replace_session(self, session_state: dict[str, Any]) -> None:
        self._session_state = deepcopy(session_state)
        self._session_state.setdefault("scene_pool", [])
        self._session_state.setdefault("recent_messages", [])
        self._session_state.setdefault("decision_history", [])
        self._session_state.setdefault("turn_count", 0)


def build_visible_state(session_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": session_state.get("mode", "exploration"),
        "current_time": deepcopy(session_state.get("current_time", {})),
        "player": deepcopy(session_state.get("player_state", {})),
        "nearby_npcs": [
            deepcopy(entity)
            for entity in session_state.get("scene_pool", [])
            if entity.get("entity_type") == "actor" or entity.get("kind") == "npc"
        ],
        "scene_pool": deepcopy(session_state.get("scene_pool", [])),
    }


def append_message(
    session_state: dict[str, Any],
    role: str,
    text: str,
    change_summary: list[dict[str, str]] | None = None,
) -> None:
    message: dict[str, Any] = {"role": role, "text": text}
    if change_summary:
        message["change_summary"] = deepcopy(change_summary)
    session_state.setdefault("recent_messages", []).append(message)


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
