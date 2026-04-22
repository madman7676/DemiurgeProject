"""Transforms structured outcomes into narrative text."""

from __future__ import annotations

import json
from pathlib import Path

from backend.modules.action_evaluation.schemas.action_evaluation_contracts import (
    ActionProcessingContract,
)
from backend.modules.llm_connector.services.llm_client import LLMAdapter
from backend.modules.router.schemas.router_contracts import RouteDecision


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "narration.txt"


class NarratorService:
    """Render player-facing narration while keeping LLM calls isolated."""

    def __init__(self, llm_adapter: LLMAdapter) -> None:
        self._llm_adapter = llm_adapter
        self._system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def render_narrative(
        self,
        action_result: ActionProcessingContract,
        visible_state: dict,
        route_decision: RouteDecision,
    ) -> str:
        """Convert a structured action result into a short narrative response."""

        prompt_payload = {
            "raw_player_input": action_result["raw_player_input"],
            "action_category": route_decision["action_category"],
            "interpreted_intent": action_result["interpreted_intent"],
            "outcome_summary": action_result["outcome_summary"],
            "time_cost": action_result["time_cost"],
            "npc_reactions": action_result["npc_reactions"],
            "player_location": visible_state["player"]["current_location"],
            "narration_notes": action_result["narration_notes"],
        }
        llm_response = self._llm_adapter.generate_text(
            system_prompt=self._system_prompt,
            user_prompt=json.dumps(prompt_payload, ensure_ascii=True),
        )

        text = llm_response["text"].strip()
        if text:
            return text

        return self._render_fallback_narrative(action_result)

    def _render_fallback_narrative(self, action_result: ActionProcessingContract) -> str:
        """Fallback narration used when the local LLM is unavailable."""

        fragments = [action_result["outcome_summary"]]

        if action_result["npc_reactions"]:
            fragments.append(action_result["npc_reactions"][0]["summary"])

        time_cost = action_result["time_cost"]
        fragments.append(
            f"The moment costs {int(time_cost['amount'])} minute(s) of in-world time."
        )
        return " ".join(fragments)
