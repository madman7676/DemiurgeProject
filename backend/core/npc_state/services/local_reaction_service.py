"""Minimal nearby-NPC reaction logic for exploration mode."""

from __future__ import annotations

from typing import Any

from backend.modules.action_evaluation.schemas.action_evaluation_contracts import NPCReaction


def build_local_npc_reactions(
    raw_player_input: str,
    action_category: str,
    nearby_npcs: list[dict[str, Any]],
    player_location: dict[str, Any],
) -> list[NPCReaction]:
    """Create placeholder reactions for NPCs already near the player."""

    lowered_input = raw_player_input.lower()
    player_region = player_location["region_id"]
    reactions: list[NPCReaction] = []

    for npc in nearby_npcs:
        if npc["location"]["region_id"] != player_region:
            continue

        npc_name = npc["identity"]["name"].lower()
        is_addressed = npc_name in lowered_input or action_category in {"speech", "question"}

        if not is_addressed and action_category not in {"inspection", "idle"}:
            continue

        if any(keyword in lowered_input for keyword in ["threaten", "attack", "kill", "fight"]):
            reaction_type = "guarded"
            summary = f"{npc['identity']['name']} stiffens and keeps a wary eye on you."
        elif any(keyword in lowered_input for keyword in ["hello", "ask", "speak", "talk", "please"]):
            reaction_type = "attentive"
            summary = f"{npc['identity']['name']} gives you their attention."
        elif action_category == "inspection":
            reaction_type = "watched"
            summary = f"{npc['identity']['name']} notices your careful attention."
        else:
            reaction_type = "curious"
            summary = f"{npc['identity']['name']} watches to see what you will do next."

        reactions.append(
            {
                "npc_id": npc["identity"]["npc_id"],
                "reaction_type": reaction_type,
                "summary": summary,
            }
        )
        break

    return reactions
