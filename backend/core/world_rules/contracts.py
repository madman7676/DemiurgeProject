"""Core contracts for structured world-definition data.

These contracts describe JSON-friendly shapes only. They intentionally avoid
runtime logic, persistence concerns, and content generation behavior.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


RulePriority = Literal["low", "medium", "high"]


class WorldIdentity(TypedDict):
    """Stable identity metadata for the world definition."""

    world_id: str
    name: str
    summary: str
    primary_genre: str
    tone_tags: list[str]


class HardRule(TypedDict):
    """Non-negotiable setting constraints that should not be broken."""

    rule_id: str
    title: str
    description: str
    priority: RulePriority


class SoftRule(TypedDict):
    """Preferred world behaviors that may bend under strong circumstances."""

    rule_id: str
    title: str
    description: str
    priority: RulePriority


class MetaRule(TypedDict):
    """Lower-priority global modifier that can influence multiple systems."""

    rule_id: str
    title: str
    description: str
    affected_systems: list[str]
    modifier_note: NotRequired[str]


class RegionDefinition(TypedDict):
    """High-level world region definition used by navigation and narration."""

    region_id: str
    name: str
    summary: str
    tags: list[str]
    connected_region_ids: NotRequired[list[str]]


class TimeModel(TypedDict):
    """Structured description of how world time is measured."""

    calendar_name: str
    base_unit: str
    cycle_unit: str
    units_per_cycle: int
    named_phases: NotRequired[list[str]]


class EvolutionSettings(TypedDict):
    """Settings that control when world evolution checks should occur."""

    enabled: bool
    default_time_threshold: int
    threshold_unit: str
    update_strategy: str


class ActiveFeatureReference(TypedDict):
    """Declares which feature modules are active in this world."""

    feature_id: str
    enabled: bool
    notes: NotRequired[str]


class DiscoveredRuleCandidate(TypedDict):
    """Candidate rule inferred during play before becoming a stable rule."""

    candidate_id: str
    title: str
    description: str
    source: str
    confidence: float
    merge_status: Literal["pending", "accepted", "rejected"]
    related_systems: NotRequired[list[str]]


class WorldRulesDocument(TypedDict):
    """Top-level JSON document for world definition data."""

    identity: WorldIdentity
    hard_rules: list[HardRule]
    soft_rules: list[SoftRule]
    regions: list[RegionDefinition]
    time_model: TimeModel
    evolution_settings: EvolutionSettings
    active_features: list[ActiveFeatureReference]
    meta_rules: list[MetaRule]
    extra: NotRequired[dict[str, Any]]
