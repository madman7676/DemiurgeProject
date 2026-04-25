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

    updated_result["outcome_summary"] = _build_outcome_summary(updated_result, action_category)
    if action_category == "combat_attempt":
        updated_result["narration_notes"].append(
            "Acknowledge the attempted aggression without entering combat mode."
        )

    logger.info("Final outcome summary: %s", updated_result["outcome_summary"])
    return updated_result


def _build_outcome_summary(
    action_result: ActionProcessingContract,
    action_category: str,
) -> str:
    """Build a concise consequence summary from Judge output."""

    summary = action_result["attempt_summary"].strip() or "Unable to evaluate action."
    if action_result["action_result"] == "blocked" and action_result["blockers"]:
        summary = f"{summary} Blocked by: {action_result['blockers'][0]}."
    elif action_result["what_succeeds"]:
        summary = f"{summary} Success focus: {action_result['what_succeeds'][0]}."
    elif action_result["what_fails"]:
        summary = f"{summary} Failure focus: {action_result['what_fails'][0]}."

    if action_result["side_effects"]:
        summary = f"{summary} Side effect: {action_result['side_effects'][0]}."
    if action_result["revealed_information"]:
        summary = f"{summary} Discovery: {action_result['revealed_information'][0]}."
    if action_category == "combat_attempt":
        summary = f"{summary} Exploration mode prevents combat resolution."
    return summary
