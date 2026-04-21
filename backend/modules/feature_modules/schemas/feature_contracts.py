"""Contracts for pluggable gameplay feature definitions."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


DisplayMode = Literal["panel", "inline", "hidden"]
VisibilityMode = Literal["always", "conditional", "internal"]


class FeatureSpecificRule(TypedDict):
    """Optional rule fragment owned by a feature module."""

    rule_id: str
    title: str
    description: str


class FeatureModuleDefinition(TypedDict):
    """Minimal registry contract for a pluggable gameplay feature."""

    feature_id: str
    name: str
    description: str
    routing_hooks: list[str]
    state_hooks: list[str]
    display_mode: DisplayMode
    visibility: VisibilityMode
    feature_rules: NotRequired[list[FeatureSpecificRule]]
    extra: NotRequired[dict[str, Any]]
