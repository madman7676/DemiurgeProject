"""Judge v1.1 implementation for structured action resolution."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.core.game_state.contracts import GameSessionState
from backend.modules.action_evaluation.schemas.action_evaluation_contracts import (
    ActionProcessingContract,
    InterpretedIntent,
    StateIntentSignals,
    TimeHints,
)
from backend.modules.action_evaluation.services.time_cost_service import estimate_time_cost
from backend.modules.llm_connector.services.llm_client import LLMAdapter
from backend.modules.router.schemas.router_contracts import RouteDecision


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "intent_interpretation.txt"
logger = logging.getLogger(__name__)

VALID_ACTION_RESULTS = {"success", "failure", "partial_success", "blocked", "mixed"}
VALID_DURATION_CLASSES = {"instant", "short", "medium", "long", "extended"}
VALID_EFFORT_LEVELS = {"low", "medium", "high"}


class ActionEvaluationService:
    """Resolve a routed player action into Judge v1.1 structured output."""

    def __init__(self, llm_adapter: LLMAdapter) -> None:
        self._llm_adapter = llm_adapter
        self._system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def evaluate_action(
        self,
        raw_player_input: str,
        route_decision: RouteDecision,
        session_state: GameSessionState,
    ) -> ActionProcessingContract:
        """Evaluate one player action and return validated structured output."""

        logger.info("Judge evaluating raw player input: %s", raw_player_input)
        expanded_player_intent = route_decision["expanded_player_intent"]
        judge_input = self._build_judge_input(
            raw_player_input=raw_player_input,
            expanded_player_intent=expanded_player_intent,
            route_decision=route_decision,
            session_state=session_state,
        )
        logger.info("Judge input primary intent: %s", route_decision["primary_intent"])
        llm_response = self._llm_adapter.generate_text(
            system_prompt=self._system_prompt,
            user_prompt=json.dumps(judge_input, ensure_ascii=False),
        )
        judge_output = self._resolve_judge_output(
            llm_text=llm_response["text"],
            raw_player_input=raw_player_input,
            expanded_player_intent=expanded_player_intent,
            route_decision=route_decision,
        )
        judge_output["time_cost"] = estimate_time_cost(judge_output)
        judge_output["outcome_summary"] = ""
        judge_output["state_changes"] = []
        judge_output["npc_reactions"] = []
        judge_output["narration_notes"] = [
            f"Route reasoning: {route_decision['routing_reason']}",
            f"Judge action result: {judge_output['action_result']}",
            f"Judge outcome quality: {judge_output['outcome_quality']}",
        ] + route_decision["narration_notes"]
        judge_output["discovered_rule_candidate"] = None
        logger.info(
            "Judge decision: action_result=%s outcome_quality=%s reasoning=%s",
            judge_output["action_result"],
            judge_output["outcome_quality"],
            judge_output["reasoning_short"],
        )
        return judge_output

    def _build_judge_input(
        self,
        raw_player_input: str,
        expanded_player_intent: str,
        route_decision: RouteDecision,
        session_state: GameSessionState,
    ) -> dict[str, Any]:
        """Build structured Judge input from the routed action and current state."""

        player_state = session_state.get("player_state", {})
        inventory = player_state.get("inventory", [])
        recent_messages = session_state.get("recent_messages", [])[-4:]
        visible_entities = [
            {
                "entity_id": npc["identity"]["npc_id"],
                "name": npc["identity"]["name"],
                "role": npc["role"],
                "location": npc["location"],
                "relationship_to_player": npc.get("relationship_to_player", {}),
            }
            for npc in session_state.get("npc_states", [])
            if npc["location"]["region_id"]
            == player_state.get("current_location", {}).get("region_id")
        ]
        return {
            "raw_player_input": raw_player_input or "",
            "router_output": route_decision,
            "game_mode": session_state.get("mode", "exploration") or "exploration",
            "scene_context": {
                "location": player_state.get("current_location", {}),
                "current_time": session_state.get("current_time", {}),
                "world_summary": session_state.get("world_rules", {}).get("identity", {}),
            },
            "player_state": player_state,
            "player_capabilities": {
                "race": player_state.get("race", "Unknown"),
                "player_class": player_state.get("player_class", "Unknown"),
                "background": player_state.get("background", ""),
                "stats": player_state.get("stats", []),
                "skills": player_state.get("skills", []),
            },
            "inventory": inventory,
            "visible_entities": visible_entities,
            "world_rules": {
                "hard_rules": session_state.get("world_rules", {}).get("hard_rules", []),
                "soft_rules": session_state.get("world_rules", {}).get("soft_rules", []),
                "meta_rules": session_state.get("world_rules", {}).get("meta_rules", []),
            },
            "recent_context": recent_messages,
            "expanded_player_intent": expanded_player_intent,
        }

    def _resolve_judge_output(
        self,
        llm_text: str,
        raw_player_input: str,
        expanded_player_intent: str,
        route_decision: RouteDecision,
    ) -> ActionProcessingContract:
        """Parse, validate, and repair Judge output where safe."""

        if llm_text.strip():
            logger.info("Judge structured output before parsing: %s", llm_text)
            try:
                cleaned_text = self._normalize_json_text(llm_text)
                parsed = json.loads(cleaned_text)
                if isinstance(parsed, dict):
                    return self._validate_judge_output(
                        parsed=parsed,
                        raw_player_input=raw_player_input,
                        expanded_player_intent=expanded_player_intent,
                        route_decision=route_decision,
                    )
            except json.JSONDecodeError:
                logger.warning("Judge parse failure. Raw response: %s", llm_text)

        return self._blocked_fallback(
            raw_player_input=raw_player_input,
            expanded_player_intent=expanded_player_intent,
            route_decision=route_decision,
        )

    def _normalize_json_text(self, raw_text: str) -> str:
        """Normalize Judge JSON output before parsing."""

        cleaned = raw_text.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            logger.info("Removed markdown code fences from Judge response.")
            cleaned = cleaned[3:-3].strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        return cleaned

    def _validate_judge_output(
        self,
        parsed: dict[str, Any],
        raw_player_input: str,
        expanded_player_intent: str,
        route_decision: RouteDecision,
    ) -> ActionProcessingContract:
        """Validate and repair model output into the required Judge schema."""

        action_result = str(parsed.get("action_result", "blocked")).strip()
        if action_result not in VALID_ACTION_RESULTS:
            action_result = "blocked"

        try:
            outcome_quality = int(parsed.get("outcome_quality", 50))
        except (TypeError, ValueError):
            outcome_quality = 50
        outcome_quality = max(0, min(100, outcome_quality))

        state_intents = self._validate_state_intents(parsed.get("state_intents", {}))
        time_hints = self._validate_time_hints(parsed.get("time_hints", {}))

        interpreted_intent: InterpretedIntent = {
            "primary_goal": route_decision["primary_intent"] or expanded_player_intent,
            "target_ids": route_decision["possible_targets"],
            "approach": route_decision["action_category"],
            "notes": route_decision["secondary_elements"],
        }

        attempt_summary = str(parsed.get("attempt_summary", "")).strip()
        if not attempt_summary:
            attempt_summary = "Unable to evaluate action."
            action_result = "blocked"

        return {
            "action_type": route_decision["action_category"],
            "raw_player_input": raw_player_input,
            "expanded_player_intent": expanded_player_intent,
            "interpreted_intent": interpreted_intent,
            "action_result": action_result,
            "outcome_quality": outcome_quality,
            "attempt_summary": attempt_summary,
            "what_succeeds": self._coerce_string_list(parsed.get("what_succeeds", [])),
            "what_fails": self._coerce_string_list(parsed.get("what_fails", [])),
            "blockers": self._coerce_string_list(parsed.get("blockers", [])),
            "side_effects": self._coerce_string_list(parsed.get("side_effects", [])),
            "revealed_information": self._coerce_string_list(parsed.get("revealed_information", [])),
            "risk_flags": self._coerce_string_list(parsed.get("risk_flags", [])),
            "state_intents": state_intents,
            "time_hints": time_hints,
            "reasoning_short": str(parsed.get("reasoning_short", "")).strip()
            or "Judge output repaired from incomplete model response.",
            "outcome_summary": "",
            "state_changes": [],
            "npc_reactions": [],
            "time_cost": {"amount": 0, "unit": "minute"},
            "narration_notes": [],
            "discovered_rule_candidate": None,
        }

    def _validate_state_intents(self, value: object) -> StateIntentSignals:
        """Validate Judge state intent payload."""

        data = value if isinstance(value, dict) else {}
        position_change = data.get("position_change")
        return {
            "position_change": str(position_change).strip() if position_change not in {None, ""} else None,
            "resource_changes": data.get("resource_changes", {}) if isinstance(data.get("resource_changes", {}), dict) else {},
            "status_changes": self._coerce_string_list(data.get("status_changes", [])),
            "relationship_signals": self._coerce_string_list(data.get("relationship_signals", [])),
            "environment_changes": self._coerce_string_list(data.get("environment_changes", [])),
        }

    def _validate_time_hints(self, value: object) -> TimeHints:
        """Validate Judge time-hint payload."""

        data = value if isinstance(value, dict) else {}
        duration_class = str(data.get("duration_class", "short")).strip()
        effort_level = str(data.get("effort_level", "medium")).strip()
        if duration_class not in VALID_DURATION_CLASSES:
            duration_class = "short"
        if effort_level not in VALID_EFFORT_LEVELS:
            effort_level = "medium"
        return {
            "duration_class": duration_class,
            "effort_level": effort_level,
            "interrupted": bool(data.get("interrupted", False)),
        }

    def _coerce_string_list(self, value: object) -> list[str]:
        """Normalize a possible string list into safe output."""

        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _blocked_fallback(
        self,
        raw_player_input: str,
        expanded_player_intent: str,
        route_decision: RouteDecision,
    ) -> ActionProcessingContract:
        """Return the required safe blocked fallback result."""

        return {
            "action_type": route_decision["action_category"],
            "raw_player_input": raw_player_input,
            "expanded_player_intent": expanded_player_intent,
            "interpreted_intent": {
                "primary_goal": route_decision["primary_intent"] or expanded_player_intent or raw_player_input,
                "target_ids": route_decision["possible_targets"],
                "approach": route_decision["action_category"],
                "notes": route_decision["secondary_elements"],
            },
            "action_result": "blocked",
            "outcome_quality": 50,
            "attempt_summary": "Unable to evaluate action.",
            "what_succeeds": [],
            "what_fails": [],
            "blockers": ["Judge could not safely evaluate the action."],
            "side_effects": [],
            "revealed_information": [],
            "risk_flags": [],
            "state_intents": {
                "position_change": None,
                "resource_changes": {},
                "status_changes": [],
                "relationship_signals": [],
                "environment_changes": [],
            },
            "time_hints": {
                "duration_class": "short",
                "effort_level": "medium",
                "interrupted": True,
            },
            "reasoning_short": "Judge fallback used because model output was unavailable or invalid.",
            "outcome_summary": "",
            "state_changes": [],
            "npc_reactions": [],
            "time_cost": {"amount": 0, "unit": "minute"},
            "narration_notes": [],
            "discovered_rule_candidate": None,
        }
