"""Contracts for routing a player action through the backend pipeline."""

from __future__ import annotations

from typing import TypedDict


class RouteDecision(TypedDict):
    """Minimal route decision for exploration-mode action processing."""

    action_category: str
    target_modules: list[str]
    reasoning: str
