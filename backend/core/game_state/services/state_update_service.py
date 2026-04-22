"""Safe state mutations for the minimal exploration loop."""

from __future__ import annotations

from copy import deepcopy

from backend.core.game_state.contracts import GameSessionState
from backend.core.game_state.services.session_service import advance_game_time
from backend.modules.action_evaluation.schemas.action_evaluation_contracts import (
    ActionProcessingContract,
    StateChange,
)


POSITIVE_REACTIONS = {"attentive", "curious"}
NEGATIVE_REACTIONS = {"guarded", "alarmed"}


def _summarize_time_change(minutes: int) -> StateChange:
    """Describe the applied in-world time change."""

    return {
        "scope": "game_state",
        "entity_id": "current_time",
        "field": "current_time",
        "summary": f"In-world time advances by {minutes} minute(s).",
    }


def _apply_npc_reaction_changes(
    session_state: GameSessionState,
    action_result: ActionProcessingContract,
) -> list[StateChange]:
    """Apply small local relationship changes caused by nearby NPC reactions."""

    state_changes: list[StateChange] = []

    for reaction in action_result["npc_reactions"]:
        matching_npc = next(
            (npc for npc in session_state["npc_states"] if npc["identity"]["npc_id"] == reaction["npc_id"]),
            None,
        )
        if not matching_npc:
            continue

        relationship = matching_npc["relationship_to_player"]
        current_trust = relationship.get("trust", 0)
        current_tension = relationship.get("tension", 0)

        if reaction["reaction_type"] in POSITIVE_REACTIONS:
            relationship["trust"] = current_trust + 1
            state_changes.append(
                {
                    "scope": "npc_state",
                    "entity_id": reaction["npc_id"],
                    "field": "relationship_to_player.trust",
                    "summary": "A nearby NPC becomes slightly more trusting.",
                }
            )
        elif reaction["reaction_type"] in NEGATIVE_REACTIONS:
            relationship["tension"] = current_tension + 1
            state_changes.append(
                {
                    "scope": "npc_state",
                    "entity_id": reaction["npc_id"],
                    "field": "relationship_to_player.tension",
                    "summary": "A nearby NPC becomes slightly more wary.",
                }
            )

    return state_changes


def apply_state_updates(
    session_state: GameSessionState,
    action_result: ActionProcessingContract,
) -> ActionProcessingContract:
    """Apply safe state updates and enrich the action result with change summaries."""

    updated_result = deepcopy(action_result)
    time_minutes = int(updated_result["time_cost"]["amount"])
    session_state["current_time"] = advance_game_time(
        session_state["current_time"],
        time_minutes,
    )
    session_state["turn_count"] += 1

    state_changes = [_summarize_time_change(time_minutes)]
    state_changes.extend(_apply_npc_reaction_changes(session_state, updated_result))
    updated_result["state_changes"] = state_changes
    return updated_result

