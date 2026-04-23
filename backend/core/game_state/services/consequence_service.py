"""Build minimal structured consequences for exploration actions."""

from __future__ import annotations

from copy import deepcopy
import logging

from backend.core.game_state.contracts import GameSessionState
from backend.core.npc_state.services.local_reaction_service import (
    build_local_npc_reactions,
)
from backend.modules.action_evaluation.schemas.action_evaluation_contracts import (
    ActionProcessingContract,
)

logger = logging.getLogger(__name__)


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

    primary_goal = updated_result["interpreted_intent"].get("primary_goal", "").strip()
    raw_input = updated_result["raw_player_input"].strip()
    expanded_input = updated_result["expanded_player_intent"].strip()

    if action_category == "combat_attempt":
        updated_result["outcome_summary"] = (
            "The action veers toward combat, but only exploration actions are "
            "supported in this prototype."
        )
        updated_result["narration_notes"].append(
            "Acknowledge the attempted aggression without entering combat mode."
        )
    elif action_category == "movement":
        updated_result["outcome_summary"] = (
            f"You attempt to move with a clear destination in mind: {primary_goal or expanded_input or raw_input}."
        )
    elif action_category == "speech":
        updated_result["outcome_summary"] = (
            f"You speak plainly and try to make contact: {primary_goal or expanded_input or raw_input}."
        )
    elif action_category == "question":
        updated_result["outcome_summary"] = (
            f"You ask for clarity about what is happening: {primary_goal or expanded_input or raw_input}."
        )
    elif action_category == "inspection":
        updated_result["outcome_summary"] = (
            f"You pause to study the scene more closely: {primary_goal or expanded_input or raw_input}."
        )
    elif action_category == "idle":
        updated_result["outcome_summary"] = (
            f"You let a brief stretch of time pass while staying alert: {primary_goal or expanded_input or raw_input}."
        )
    else:
        updated_result["outcome_summary"] = (
            f"You act on a simple exploratory impulse: {primary_goal or expanded_input or raw_input}."
        )

    logger.info("Final outcome summary: %s", updated_result["outcome_summary"])
    return updated_result
