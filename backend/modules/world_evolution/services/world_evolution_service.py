"""Updates world state after time thresholds or scheduled changes."""

from __future__ import annotations

from backend.core.game_state.contracts import GameSessionState
from backend.modules.world_evolution.schemas.world_evolution_contracts import (
    WorldEvolutionCheckResult,
)


def check_world_evolution_hook(session_state: GameSessionState) -> WorldEvolutionCheckResult:
    """Check whether a future world-evolution threshold has been reached."""

    threshold_minutes = session_state["world_rules"]["evolution_settings"]["default_time_threshold"] * 60
    total_minutes = (
        ((session_state["current_time"]["day"] - 1) * 24 * 60)
        + (session_state["current_time"]["hour"] * 60)
        + session_state["current_time"]["minute"]
    )
    threshold_reached = total_minutes % max(threshold_minutes, 1) == 0

    if threshold_reached:
        session_state["last_evolution_check_turn"] = session_state["turn_count"]

    return {
        "threshold_reached": threshold_reached,
        "threshold_minutes": threshold_minutes,
        "note": (
            "Evolution threshold reached; future world updates can be triggered here."
            if threshold_reached
            else "No evolution threshold reached on this action."
        ),
    }

