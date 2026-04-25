"""Contracts for Judge v1.1 action resolution and downstream processing."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from backend.core.world_rules.contracts import DiscoveredRuleCandidate


ActionResult = Literal["success", "failure", "partial_success", "blocked", "mixed"]
DurationClass = Literal["instant", "short", "medium", "long", "extended"]
EffortLevel = Literal["low", "medium", "high"]


class InterpretedIntent(TypedDict):
    """Normalized meaning extracted from routed player input."""

    primary_goal: str
    target_ids: list[str]
    approach: str
    notes: list[str]


class StateIntentSignals(TypedDict):
    """Structured state-change intent emitted by Judge."""

    position_change: str | None
    resource_changes: dict[str, Any]
    status_changes: list[str]
    relationship_signals: list[str]
    environment_changes: list[str]


class TimeHints(TypedDict):
    """Structured hints used by the time-cost evaluator."""

    duration_class: DurationClass
    effort_level: EffortLevel
    interrupted: bool


class StateChange(TypedDict):
    """Minimal applied or intended state change summary."""

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


class ActingCharacterInput(TypedDict):
    """Actor-centric snapshot passed into Judge for one attempted action."""

    name: str
    description: str
    state: dict[str, Any]
    capabilities: dict[str, Any]
    inventory: list[dict[str, Any]]
    known_facts: list[str]
    relationships: dict[str, Any]


class ActionEvaluationInput(TypedDict):
    """Structured Judge input used for LLM evaluation."""

    raw_input: str
    attempted_action: str
    acting_character: ActingCharacterInput
    router_output: dict[str, Any]
    game_mode: str
    scene_context: dict[str, Any]
    visible_entities: list[dict[str, Any]]
    world_rules: dict[str, Any]
    recent_context: list[dict[str, Any]]
    raw_player_input: NotRequired[str]
    expanded_player_intent: NotRequired[str]
    player_state: NotRequired[dict[str, Any]]
    player_capabilities: NotRequired[dict[str, Any]]
    inventory: NotRequired[list[dict[str, Any]]]


class ActionProcessingContract(TypedDict):
    """Judge result plus downstream-resolved fields for one player action."""

    action_type: str
    raw_player_input: str
    expanded_player_intent: str
    interpreted_intent: InterpretedIntent
    action_result: ActionResult
    outcome_quality: int
    attempt_summary: str
    what_succeeds: list[str]
    what_fails: list[str]
    blockers: list[str]
    side_effects: list[str]
    proposed_side_effects: list[str]
    applied_side_effects: list[str]
    quality_side_effect_chance: float
    quality_side_effect_applied: bool
    revealed_information: list[str]
    risk_flags: list[str]
    state_intents: StateIntentSignals
    time_hints: TimeHints
    reasoning_short: str
    outcome_summary: str
    state_changes: list[StateChange]
    npc_reactions: list[NPCReaction]
    time_cost: TimeCost
    narration_notes: list[str]
    discovered_rule_candidate: DiscoveredRuleCandidate | None
