"""Contracts for lightweight world-evolution threshold checks."""

from __future__ import annotations

from typing import TypedDict


class WorldEvolutionCheckResult(TypedDict):
    """Structured placeholder for future world-evolution processing."""

    threshold_reached: bool
    threshold_minutes: int
    note: str
