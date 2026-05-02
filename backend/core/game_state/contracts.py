"""Contracts for session-level game state and visible frontend data."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from backend.core.npc_state.contracts import NPCStateContract
from backend.core.player_state.contracts import PlayerStateContract
from backend.core.world_rules.contracts import DiscoveredRuleCandidate, WorldRulesDocument


class QuickChoice(TypedDict):
    """Previously presented player choice that can be referenced tersely."""

    choice_id: str
    label: str
    intent_text: str


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
    annotations: NotRequired[list[dict[str, Any]]]
    change_summary: NotRequired[list[dict[str, str]]]


class SceneEntityPoolEntry(TypedDict):
    """Soft scene-memory entity available for local resolution only."""

    entity_type: Literal["scene_entity", "interactable"]
    entity_id: str
    name: str
    normalized_name: NotRequired[str]
    aliases: list[str]
    source: str
    status: NotRequired[Literal["available", "background"]]
    truth_status: NotRequired[Literal["soft_scene"]]
    scene_id: NotRequired[str]
    location_id: NotRequired[str]
    first_seen_turn: NotRequired[int]
    last_seen_turn: NotRequired[int]
    mention_count: NotRequired[int]
    raw: dict[str, Any]


class ScenePoolAnchor(TypedDict):
    """Tracks when the soft scene pool should be refreshed."""

    region_id: str
    detail: str
    turn: int


class AvailableSceneEntityCandidate(TypedDict):
    """Temporary v1 scene entity candidate emitted by narrator markers."""

    name: str
    normalized_name: NotRequired[str]
    source: str
    status: str


class ReferencePoolEntry(TypedDict):
    """Known off-scene reference mentioned by narration."""

    reference_id: str
    name: str
    normalized_name: str
    status: Literal["known_reference"]
    availability: Literal["not_present"]
    first_seen_turn: int
    last_seen_turn: int
    mention_count: int


class DecisionEvent(TypedDict):
    """Short developer-facing description of a gameplay pipeline decision."""

    source: str
    message: str
    details: dict[str, object]


class DecisionCycle(TypedDict):
    """Decision events collected for one processed player message."""

    turn: int
    raw_player_input: str
    events: list[DecisionEvent]


class VisibleGameState(TypedDict):
    """Visible state returned to the frontend after each action."""

    mode: Literal["exploration"]
    current_time: GameTime
    player: PlayerStateContract
    nearby_npcs: list[dict[str, Any]]
    scene_pool: NotRequired[list[dict[str, Any]]]


class GameSessionState(TypedDict):
    """In-memory session state for the minimal gameplay loop."""

    session_id: str
    mode: Literal["exploration"]
    world_rules: WorldRulesDocument
    player_state: PlayerStateContract
    npc_states: list[NPCStateContract]
    current_time: GameTime
    discovered_rules: list[DiscoveredRuleCandidate]
    last_presented_choices: list[QuickChoice]
    recent_messages: list[SessionMessage]
    decision_history: list[DecisionCycle]
    scene_pool: list[SceneEntityPoolEntry]
    scene_entity_pool: list[SceneEntityPoolEntry]
    available_scene_entities: list[AvailableSceneEntityCandidate]
    reference_pool: list[ReferencePoolEntry]
    output_language: NotRequired[str]
    scene_pool_anchor: ScenePoolAnchor
    interruption_pressure: int
    turn_count: int
    last_evolution_check_turn: int
