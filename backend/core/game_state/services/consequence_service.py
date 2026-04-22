"""Build minimal structured consequences for exploration actions."""

from __future__ import annotations

from copy import deepcopy

from backend.core.game_state.contracts import GameSessionState
from backend.core.npc_state.services.local_reaction_service import (
    build_local_npc_reactions,
)
from backend.modules.action_evaluation.schemas.action_evaluation_contracts import (
    ActionProcessingContract,
)


def apply_consequence_layer(
    session_state: GameSessionState,
    action_result: ActionProcessingContract,
    action_category: str,
) -> ActionProcessingContract:
    """Attach lightweight consequences before persistent state updates."""

    updated_result = deepcopy(action_result)
    npc_reactions = build_local_npc_reactions(
        raw_player_input=updated_result["raw_player_input"],
        action_category=action_category,
        nearby_npcs=session_state["npc_states"],
        player_location=session_state["player_state"]["current_location"],
    )
    updated_result["npc_reactions"] = npc_reactions

    if action_category == "combat_attempt":
        updated_result["outcome_summary"] = (
            "The action veers toward combat, but only exploration actions are "
            "supported in this prototype."
        )
        updated_result["narration_notes"].append(
            "Acknowledge the attempted aggression without entering combat mode."
        )
    elif action_category == "move":
        updated_result["outcome_summary"] = (
            "The player spends time repositioning and reorienting within the current area."
        )
    elif action_category == "talk":
        updated_result["outcome_summary"] = (
            "The player directs attention toward a nearby character and invites a response."
        )
    elif action_category == "observe":
        updated_result["outcome_summary"] = (
            "The player slows down to inspect the scene and gather details."
        )
    elif action_category == "wait":
        updated_result["outcome_summary"] = (
            "The player pauses, lets time pass, and watches for subtle shifts."
        )
    else:
        updated_result["outcome_summary"] = (
            "The player tests the space carefully and waits to see what changes."
        )

    return updated_result

