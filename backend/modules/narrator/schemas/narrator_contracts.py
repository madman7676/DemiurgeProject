"""Contracts for structured narration requests and responses."""

from __future__ import annotations

from typing import TypedDict


class NarrationRequest(TypedDict):
    """Minimal input required to render player-facing narrative text."""

    action_category: str
    outcome_summary: str
    narration_notes: list[str]


class NarrationResponse(TypedDict):
    """Narrative text returned to the API and frontend."""

    narrative_text: str
