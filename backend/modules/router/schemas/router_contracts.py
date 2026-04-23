"""Contracts for routing a player action through the backend pipeline."""

from __future__ import annotations

from typing import Literal, TypedDict

from backend.core.game_state.contracts import QuickChoice


class SceneContextSummary(TypedDict):
    """Short structured scene summary provided to the Router Agent."""

    game_mode: str
    location: str
    time_summary: str


class VisibleEntitySummary(TypedDict):
    """Short structured summary of a visible entity."""

    entity_id: str
    name: str
    role: str


class RouterAgentInput(TypedDict):
    """Structured input for the LLM-driven Router Agent."""

    raw_player_input: str
    game_mode: str
    scene_context: SceneContextSummary
    visible_entities_summary: list[VisibleEntitySummary]
    available_modules: list[str]
    last_presented_choices: list[QuickChoice]
    active_features: list[str]


class RouteDecision(TypedDict):
    """Structured Router Agent output used by the exploration pipeline."""

    action_category: Literal["speech", "inspection", "movement", "question", "idle", "combat_attempt"]
    expanded_player_intent: str
    primary_intent: str
    secondary_elements: list[str]
    possible_targets: list[str]
    requested_agents: list[str]
    narration_notes: list[str]
    routing_reason: str
