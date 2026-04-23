"""Evaluates whether an action is possible and how likely it is."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.core.game_state.contracts import GameSessionState
from backend.modules.action_evaluation.schemas.action_evaluation_contracts import (
    ActionProcessingContract,
    InterpretedIntent,
)
from backend.modules.action_evaluation.services.time_cost_service import estimate_time_cost
from backend.modules.llm_connector.services.llm_client import LLMAdapter
from backend.modules.router.schemas.router_contracts import RouteDecision


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "intent_interpretation.txt"
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ActionEvaluationService:
    """Create an initial structured action contract for exploration mode."""

    def __init__(self, llm_adapter: LLMAdapter) -> None:
        self._llm_adapter = llm_adapter
        self._system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def evaluate_action(
        self,
        raw_player_input: str,
        route_decision: RouteDecision,
        session_state: GameSessionState,
    ) -> ActionProcessingContract:
        """Interpret the action, estimate feasibility, and attach time cost."""

        logger.info("Evaluating raw player input: %s", raw_player_input)
        expanded_player_intent = route_decision["expanded_player_intent"]
        interpreted_intent = self._interpret_intent(
            raw_player_input=raw_player_input,
            expanded_player_intent=expanded_player_intent,
            route_decision=route_decision,
            action_category=route_decision["action_category"],
            session_state=session_state,
        )
        logger.info("Interpreted intent: %s", interpreted_intent)
        time_cost = estimate_time_cost(
            action_category=route_decision["action_category"],
            raw_player_input=expanded_player_intent,
            interpreted_intent=interpreted_intent,
        )
        roll_needed = self._roll_needed(route_decision["action_category"], raw_player_input)
        feasibility_score = self._feasibility_score(
            action_category=route_decision["action_category"],
            raw_player_input=raw_player_input,
        )

        return {
            "action_type": route_decision["action_category"],
            "raw_player_input": raw_player_input,
            "expanded_player_intent": expanded_player_intent,
            "interpreted_intent": interpreted_intent,
            "feasibility_score": feasibility_score,
            "roll_needed": roll_needed,
            "outcome_summary": "",
            "state_changes": [],
            "npc_reactions": [],
            "time_cost": time_cost,
            "narration_notes": [
                f"Route reasoning: {route_decision['routing_reason']}",
                "Keep the response focused on exploration mode.",
            ]
            + route_decision["narration_notes"],
        }

    def _interpret_intent(
        self,
        raw_player_input: str,
        expanded_player_intent: str,
        route_decision: RouteDecision,
        action_category: str,
        session_state: GameSessionState,
    ) -> InterpretedIntent:
        """Interpret a player action through the LLM boundary with a safe fallback."""

        visible_context = {
            "location": session_state["player_state"]["current_location"],
            "nearby_npcs": [
                npc["identity"]["name"]
                for npc in session_state["npc_states"]
                if npc["location"]["region_id"]
                == session_state["player_state"]["current_location"]["region_id"]
            ],
        }
        prompt_payload = {
            "action_category": action_category,
            "raw_player_input": raw_player_input,
            "expanded_player_intent": expanded_player_intent,
            "router_primary_intent": route_decision["primary_intent"],
            "router_possible_targets": route_decision["possible_targets"],
            "visible_context": visible_context,
        }
        llm_response = self._llm_adapter.generate_text(
            system_prompt=self._system_prompt,
            user_prompt=json.dumps(prompt_payload, ensure_ascii=True),
        )
        if llm_response["text"].strip():
            logger.info("Structured LLM output before parsing: %s", llm_response["text"])
            try:
                cleaned_text = self._normalize_json_text(llm_response["text"])
                parsed = json.loads(cleaned_text)
                return {
                    "primary_goal": parsed.get("primary_goal", "explore"),
                    "target_ids": parsed.get("target_ids", []),
                    "approach": parsed.get("approach", action_category),
                    "notes": parsed.get("notes", []),
                }
            except json.JSONDecodeError:
                logger.warning(
                    "Failed to parse structured LLM output. Raw response: %s",
                    llm_response["text"],
                )

        return self._fallback_intent(
            expanded_player_intent,
            action_category,
            visible_context["nearby_npcs"],
        )

    def _normalize_json_text(self, raw_text: str) -> str:
        """Normalize LLM JSON output before parsing."""

        cleaned = raw_text.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            logger.info("Removed markdown code fences from LLM JSON response.")
            cleaned = cleaned[3:-3].strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        return cleaned

    def _fallback_intent(
        self,
        raw_player_input: str,
        action_category: str,
        nearby_npcs: list[str],
    ) -> InterpretedIntent:
        """Simple deterministic intent extraction for local development."""

        lowered = raw_player_input.lower()
        target_ids = [name for name in nearby_npcs if name.lower() in lowered]
        primary_goal_map = {
            "speech": "greet nearby person",
            "question": "ask for information",
            "inspection": "inspect surroundings",
            "movement": "move to a nearby direction or area",
            "idle": "let time pass",
            "combat_attempt": "attempt_combat",
        }
        return {
            "primary_goal": primary_goal_map.get(action_category, raw_player_input.strip()),
            "target_ids": target_ids,
            "approach": action_category,
            "notes": [f"Fallback interpretation for input: {raw_player_input.strip()}"],
        }

    def _roll_needed(self, action_category: str, raw_player_input: str) -> bool:
        """Flag obviously uncertain actions without implementing full roll logic."""

        lowered = raw_player_input.lower()
        risky_keywords = ["convince", "steal", "sneak", "climb", "force"]
        return action_category in {"speech", "question"} and any(
            keyword in lowered for keyword in risky_keywords
        )

    def _feasibility_score(self, action_category: str, raw_player_input: str) -> float:
        """Return a small heuristic feasibility estimate."""

        lowered = raw_player_input.lower()
        if action_category == "combat_attempt":
            return 0.1
        if any(keyword in lowered for keyword in ["impossible", "teleport", "instantly"]):
            return 0.25
        if action_category in {"inspection", "speech", "question", "idle"}:
            return 0.85
        if action_category == "movement":
            return 0.75
        return 0.65
