"""In-memory session store and visible state helpers."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.core.game_state.contracts import (
    DecisionCycle,
    GameSessionState,
    GameTime,
    ScenePoolAnchor,
    SessionMessage,
    VisibleGameState,
)


DATA_DIR = Path(__file__).resolve().parents[2]


def _load_json(relative_path: str) -> Any:
    """Load static example data used for the initial in-memory session."""

    file_path = DATA_DIR / relative_path
    return json.loads(file_path.read_text(encoding="utf-8"))


def _create_initial_time() -> GameTime:
    """Return the starting exploration time."""

    return {
        "year": 1,
        "month": 1,
        "day": 1,
        "hour": 8,
        "minute": 0,
    }


def _create_scene_pool_anchor(player_state: dict[str, Any]) -> ScenePoolAnchor:
    """Anchor the soft scene entity pool to the current visible location."""

    current_location = player_state.get("current_location", {})
    return {
        "region_id": str(current_location.get("region_id", "unknown")),
        "detail": str(current_location.get("detail", "")),
        "turn": 0,
    }


def create_initial_session_state() -> GameSessionState:
    """Build a single minimal session using documentation example data."""

    player_state = _load_json("player_state/data/player.example.json")
    scene_pool: list[dict[str, Any]] = []
    return {
        "session_id": f"session-{uuid4()}",
        "mode": "exploration",
        "world_rules": _load_json("world_rules/data/world.example.json"),
        "player_state": player_state,
        "npc_states": [_load_json("npc_state/data/npc.example.json")],
        "current_time": _create_initial_time(),
        "discovered_rules": [],
        "last_presented_choices": [],
        "recent_messages": [],
        "decision_history": [],
        "scene_pool": scene_pool,
        "scene_entity_pool": scene_pool,
        "available_scene_entities": [],
        "reference_pool": [],
        "output_language": "",
        "scene_pool_anchor": _create_scene_pool_anchor(player_state),
        "interruption_pressure": 0,
        "turn_count": 0,
        "last_evolution_check_turn": 0,
    }


def get_nearby_npcs(session_state: GameSessionState) -> list[dict[str, Any]]:
    """Return NPCs in the same current region as the player."""

    player_location = session_state["player_state"]["current_location"]
    player_region = player_location["region_id"]
    return [
        npc
        for npc in session_state["npc_states"]
        if npc["location"]["region_id"] == player_region
    ]


def build_visible_state(session_state: GameSessionState) -> VisibleGameState:
    """Build the lightweight state shape used by the frontend."""

    return {
        "mode": session_state["mode"],
        "current_time": deepcopy(session_state["current_time"]),
        "player": deepcopy(session_state["player_state"]),
        "nearby_npcs": deepcopy(get_nearby_npcs(session_state)),
        "scene_pool": deepcopy(session_state.get("scene_pool", session_state.get("scene_entity_pool", []))),
    }


def append_message(
    session_state: GameSessionState,
    role: SessionMessage["role"],
    text: str,
    annotations: list[dict[str, Any]] | None = None,
) -> None:
    """Append a player or assistant message to the current session."""

    message: SessionMessage = {"role": role, "text": text}
    if annotations:
        message["annotations"] = deepcopy(annotations)
    session_state["recent_messages"].append(message)


def append_decision_cycle(
    session_state: GameSessionState,
    decision_cycle: DecisionCycle,
) -> None:
    """Append one developer-facing decision cycle to the in-memory session."""

    session_state["decision_history"].append(deepcopy(decision_cycle))


def advance_game_time(current_time: GameTime, minutes_to_add: int) -> GameTime:
    """Advance canonical game time using a simple expandable calendar model."""

    minutes_per_hour = 60
    hours_per_day = 24
    days_per_month = 30
    months_per_year = 12

    updated = deepcopy(current_time)
    total_minutes = updated["minute"] + max(minutes_to_add, 0)
    updated["minute"] = total_minutes % minutes_per_hour

    carry_hours = total_minutes // minutes_per_hour
    total_hours = updated["hour"] + carry_hours
    updated["hour"] = total_hours % hours_per_day

    carry_days = total_hours // hours_per_day
    total_days = updated["day"] + carry_days
    updated["day"] = ((total_days - 1) % days_per_month) + 1

    carry_months = (total_days - 1) // days_per_month
    total_months = updated["month"] + carry_months
    updated["month"] = ((total_months - 1) % months_per_year) + 1

    carry_years = (total_months - 1) // months_per_year
    updated["year"] += carry_years
    return updated


class InMemorySessionStore:
    """Single-session store used by the minimal prototype backend."""

    def __init__(self) -> None:
        self._session_state = create_initial_session_state()

    def get_session(self) -> GameSessionState:
        """Return the current mutable in-memory session."""

        return self._session_state

    def replace_session(self, session_state: GameSessionState) -> None:
        """Replace the in-memory session with a client-provided snapshot."""

        self._session_state = deepcopy(session_state)
