"""Build minimal structured consequences for exploration actions."""

from __future__ import annotations

from copy import deepcopy
import logging
from random import Random

from backend.core.game_state.contracts import GameSessionState
from backend.core.npc_state.services.local_reaction_service import (
    build_local_npc_reactions,
)
from backend.core.game_state.services.quality_side_effects import (
    clamp_outcome_quality,
    quality_side_effect_chance,
    should_apply_quality_side_effect,
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
    _resolve_quality_side_effects(session_state, updated_result)
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


def _resolve_quality_side_effects(
    session_state: GameSessionState,
    action_result: ActionProcessingContract,
) -> None:
    """Resolve conditional Judge side effects with deterministic code-driven randomness."""

    proposed_side_effects = list(action_result.get("proposed_side_effects", action_result["side_effects"]))
    normalized_quality = clamp_outcome_quality(action_result.get("outcome_quality", 50))
    chance = quality_side_effect_chance(normalized_quality)
    seed = (
        f"{session_state['session_id']}|{session_state['turn_count'] + 1}|"
        f"{action_result['raw_player_input']}|{action_result['expanded_player_intent']}"
    )
    applied = bool(proposed_side_effects) and should_apply_quality_side_effect(
        normalized_quality,
        rng=Random(seed),
    )
    action_result["outcome_quality"] = normalized_quality
    action_result["proposed_side_effects"] = proposed_side_effects
    action_result["quality_side_effect_chance"] = chance
    action_result["quality_side_effect_applied"] = applied
    action_result["applied_side_effects"] = proposed_side_effects if applied else []
    action_result["side_effects"] = list(action_result["applied_side_effects"])

    logger.info(
        "Quality side effects: quality=%s chance=%.3f applied=%s proposed=%s",
        normalized_quality,
        chance,
        applied,
        proposed_side_effects,
    )


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

    if action_result["applied_side_effects"]:
        summary = f"{summary} Side effect: {action_result['applied_side_effects'][0]}."
    if action_result["revealed_information"]:
        summary = f"{summary} Discovery: {action_result['revealed_information'][0]}."
    if action_category == "combat_attempt":
        summary = f"{summary} Exploration mode prevents combat resolution."
    return summary
