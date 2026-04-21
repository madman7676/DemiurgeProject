"""Contracts for player-action interpretation and evaluation."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from backend.core.world_rules.contracts import DiscoveredRuleCandidate


class InterpretedIntent(TypedDict):
    """Normalized meaning extracted from raw player input."""

    primary_goal: str
    target_ids: NotRequired[list[str]]
    approach: NotRequired[str]
    notes: NotRequired[list[str]]


class RollResultPlaceholder(TypedDict):
    """Placeholder contract for future roll-based resolution data."""

    skill_id: NotRequired[str]
    difficulty: NotRequired[int | float]
    rolled_value: NotRequired[int | float]
    success: NotRequired[bool]


class StateChange(TypedDict):
    """Minimal description of a state change caused by an action."""

    scope: str
    entity_id: str
    field: str
    summary: str


class NPCReaction(TypedDict):
    """Observed or expected NPC reaction to an action."""

    npc_id: str
    reaction_type: str
    summary: str


class TimeCost(TypedDict):
    """Time consumed by an action in world-model units."""

    amount: int | float
    unit: str


class ActionProcessingContract(TypedDict):
    """Structured result produced during action processing."""

    action_type: str
    raw_player_input: str
    interpreted_intent: InterpretedIntent
    feasibility_score: float
    roll_needed: bool
    roll_result: NotRequired[RollResultPlaceholder]
    outcome_summary: str
    state_changes: list[StateChange]
    npc_reactions: list[NPCReaction]
    discovered_rule_candidate: NotRequired[DiscoveredRuleCandidate]
    time_cost: TimeCost
    narration_notes: list[str]
