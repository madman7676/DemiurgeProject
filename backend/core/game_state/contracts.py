"""Contracts for session-level game state and visible frontend data."""

from __future__ import annotations

from typing import Literal, TypedDict

from backend.core.npc_state.contracts import NPCStateContract
from backend.core.player_state.contracts import PlayerStateContract
from backend.core.world_rules.contracts import DiscoveredRuleCandidate, WorldRulesDocument


class GameTime(TypedDict):
    """Structured in-world time suitable for future calendar expansion."""

    year: int
    month: int
    day: int
    hour: int
    minute: int


class SessionMessage(TypedDict):
    """Single chat message kept in the in-memory session."""

    role: Literal["player", "assistant"]
    text: str


class VisibleGameState(TypedDict):
    """Visible state returned to the frontend after each action."""

    mode: Literal["exploration"]
    current_time: GameTime
    player: PlayerStateContract
    nearby_npcs: list[NPCStateContract]


class GameSessionState(TypedDict):
    """In-memory session state for the minimal gameplay loop."""

    session_id: str
    mode: Literal["exploration"]
    world_rules: WorldRulesDocument
    player_state: PlayerStateContract
    npc_states: list[NPCStateContract]
    current_time: GameTime
    discovered_rules: list[DiscoveredRuleCandidate]
    recent_messages: list[SessionMessage]
    turn_count: int
    last_evolution_check_turn: int

