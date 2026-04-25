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
            "expanded_player_intent": action_result["expanded_player_intent"],
            "action_category": route_decision["action_category"],
            "primary_intent": route_decision["primary_intent"],
            "interpreted_intent": action_result["interpreted_intent"],
            "action_result": action_result["action_result"],
            "outcome_quality": action_result["outcome_quality"],
            "attempt_summary": action_result["attempt_summary"],
            "what_succeeds": action_result["what_succeeds"],
            "what_fails": action_result["what_fails"],
            "blockers": action_result["blockers"],
            "side_effects": action_result["side_effects"],
            "revealed_information": action_result["revealed_information"],
            "risk_flags": action_result["risk_flags"],
            "state_intents": action_result["state_intents"],
            "reasoning_short": action_result["reasoning_short"],
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

        fragments = [action_result["attempt_summary"]]

        if action_result["action_result"] == "blocked" and action_result["blockers"]:
            fragments.append(f"Blocked by {action_result['blockers'][0]}.")
        elif action_result["what_succeeds"]:
            fragments.append(action_result["what_succeeds"][0])
        elif action_result["what_fails"]:
            fragments.append(action_result["what_fails"][0])

        if action_result["revealed_information"]:
            fragments.append(f"You learn: {action_result['revealed_information'][0]}.")

        if action_result["outcome_summary"]:
            fragments.insert(0, action_result["outcome_summary"])

        if action_result["npc_reactions"]:
            fragments.append(action_result["npc_reactions"][0]["summary"])

        time_cost = action_result["time_cost"]
        fragments.append(
            f"The moment costs {int(time_cost['amount'])} minute(s) of in-world time."
        )
        return " ".join(fragments)
