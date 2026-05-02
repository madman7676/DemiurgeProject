"""Judge v1.1 implementation for structured action resolution."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from backend.core.game_state.contracts import GameSessionState
from backend.core.game_state.services.quality_side_effects import clamp_outcome_quality
from backend.modules.action_evaluation.schemas.action_evaluation_contracts import (
    ActionEvaluationInput,
    ActionProcessingContract,
    ActingCharacterInput,
    InterpretedIntent,
    StateIntentSignals,
    TimeHints,
)
from backend.modules.entity_resolver.schemas.entity_resolver_contracts import (
    EntityResolutionResult,
)
from backend.modules.action_evaluation.services.time_cost_service import estimate_time_cost
from backend.modules.llm_connector.services.llm_client import LLMAdapter
from backend.modules.router.schemas.router_contracts import RouteDecision


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "intent_interpretation.txt"
logger = logging.getLogger(__name__)

VALID_ACTION_RESULTS = {"success", "failure", "partial_success", "blocked", "mixed"}
VALID_DURATION_CLASSES = {"instant", "short", "medium", "long", "extended"}
VALID_EFFORT_LEVELS = {"low", "medium", "high"}
APPROVED_JUDGE_FIELDS = {
    "action_result",
    "outcome_quality",
    "attempt_summary",
    "what_succeeds",
    "what_fails",
    "blockers",
    "side_effects",
    "revealed_information",
    "risk_flags",
    "state_intents",
    "time_hints",
    "reasoning_short",
}
FORBIDDEN_JUDGE_FIELDS = {
    "action_category",
    "description",
    "details",
    "observed_details",
    "potential_leads",
    "skill_check",
}
DEBUG_DUMP_DIR = Path(os.getenv("JUDGE_DEBUG_DUMP_DIR", "backend/.debug/judge"))


class ActionEvaluationService:
    """Resolve a routed player action into Judge v1.1 structured output."""

    def __init__(self, llm_adapter: LLMAdapter) -> None:
        self._llm_adapter = llm_adapter
        self._system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def evaluate_action(
        self,
        raw_player_input: str,
        route_decision: RouteDecision,
        entity_resolution: EntityResolutionResult,
        session_state: GameSessionState,
    ) -> ActionProcessingContract:
        """Evaluate one player action and return validated structured output."""

        logger.info("Judge evaluating raw player input: %s", raw_player_input)
        expanded_player_intent = route_decision["expanded_player_intent"]
        if entity_resolution["execution_status"] != "clear":
            judge_output = self._precondition_interruption(
                raw_player_input=raw_player_input,
                expanded_player_intent=expanded_player_intent,
                route_decision=route_decision,
                entity_resolution=entity_resolution,
                session_state=session_state,
            )
            judge_output["time_cost"] = estimate_time_cost(judge_output)
            return judge_output
        judge_input = self._build_judge_input(
            raw_player_input=raw_player_input,
            expanded_player_intent=expanded_player_intent,
            route_decision=route_decision,
            entity_resolution=entity_resolution,
            session_state=session_state,
        )
        logger.info("Judge input primary intent: %s", route_decision["primary_intent"])
        logger.info("Judge attempted action: %s", judge_input["attempted_action"])
        user_prompt = json.dumps(judge_input, ensure_ascii=False, indent=2)
        logger.info(
            "JudgeInput compact size: %s bytes; final prompt payload size: system=%s user=%s total=%s chars",
            len(user_prompt.encode("utf-8")),
            len(self._system_prompt),
            len(user_prompt),
            len(self._system_prompt) + len(user_prompt),
        )
        self._dump_debug_file("judge_input.json", user_prompt)
        llm_response = self._llm_adapter.generate_text(
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            format_json=True,
        )
        self._dump_debug_file("judge_raw_response.txt", llm_response["text"])
        judge_output = self._resolve_judge_output(
            llm_text=llm_response["text"],
            judge_input=judge_input,
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
        entity_resolution: EntityResolutionResult,
        session_state: GameSessionState,
    ) -> ActionEvaluationInput:
        """Build structured Judge input from the routed action and current state."""

        player_state = session_state.get("player_state", {})
        recent_messages = [
            message["text"]
            for message in session_state.get("recent_messages", [])[-3:]
        ]
        visible_relevant_entities = [
            {
                "entity_id": npc["identity"]["npc_id"],
                "name": npc["identity"]["name"],
                "role": npc["role"],
                "relationship_to_player": npc.get("relationship_to_player", {}),
            }
            for npc in session_state.get("npc_states", [])
            if npc["location"]["region_id"]
            == player_state.get("current_location", {}).get("region_id")
        ]
        acting_character = self._build_acting_character(player_state, entity_resolution)
        attempted_action = expanded_player_intent.strip() or raw_player_input.strip()
        relevant_rules = self._filter_relevant_rules(
            world_rules=session_state.get("world_rules", {}),
            attempted_action=attempted_action,
        )
        judge_input: ActionEvaluationInput = {
            "raw_player_input": raw_player_input or "",
            "attempted_action": attempted_action,
            "attempted_method": route_decision.get("attempted_method", attempted_action),
            "primary_intent": route_decision["primary_intent"],
            "action_category": route_decision["action_category"],
            "game_mode": session_state.get("mode", "exploration") or "exploration",
            "acting_character": acting_character,
            "scene_context": {
                "location_summary": self._build_location_summary(player_state),
                "environment_summary": session_state.get("world_rules", {}).get("identity", {}).get("summary", ""),
                "visible_relevant_entities": visible_relevant_entities,
                "pressure_summary": self._build_pressure_summary(session_state),
                "recent_relevant_context": recent_messages,
            },
            "entity_resolution": {
                "resolved_entities": entity_resolution["resolved_entities"],
                "unresolved_mentions": entity_resolution["unresolved_mentions"],
                "ambiguous_mentions": entity_resolution["ambiguous_mentions"],
                "annotations": entity_resolution["annotations"],
                "execution_status": entity_resolution["execution_status"],
                "resolver_status": entity_resolution.get("resolver_status", "clear"),
            },
            "prechecked_facts": {
                "blocking_facts": self._build_prechecked_blockers(entity_resolution),
                "warnings": self._build_prechecked_warnings(entity_resolution, route_decision),
                "confirmed_facts": self._build_confirmed_facts(
                    entity_resolution=entity_resolution,
                    relevant_rules=relevant_rules,
                ),
            },
        }
        logger.debug("Judge acting_character input: %s", acting_character)
        return judge_input

    def _build_acting_character(
        self,
        player_state: dict[str, Any],
        entity_resolution: EntityResolutionResult,
    ) -> ActingCharacterInput:
        """Build a compact actor snapshot without full inventory or state dumps."""

        identity = player_state.get("identity", {})
        status_effects = player_state.get("status_effects", [])
        resolved_ids = {
            entity["entity_id"]
            for entity in entity_resolution["resolved_entities"]
            if entity["truth_status"] == "hard"
        }
        relevant_inventory = [
            item
            for item in player_state.get("inventory", [])
            if item.get("item_id") in resolved_ids
        ]
        relevant_skills = [
            skill
            for skill in player_state.get("skills", [])
            if skill.get("skill_id") in resolved_ids
        ]
        return {
            "id": str(identity.get("player_id", "unknown")),
            "name": str(identity.get("name", "Unknown")).strip() or "Unknown",
            "race": player_state.get("race", "Unknown"),
            "character_class": player_state.get("player_class", "Unknown"),
            "condition_summary": self._summarize_condition(status_effects),
            "relevant_stats": player_state.get("stats", []),
            "relevant_skills": relevant_skills,
            "relevant_resources": {
                currency["currency_id"]: currency["amount"]
                for currency in player_state.get("currencies", [])
                if "currency_id" in currency and "amount" in currency
            },
            "relevant_inventory": relevant_inventory,
            "equipped_items": player_state.get("equipped_items", []) + player_state.get("held_items", []),
        }

    def _build_location_summary(self, player_state: dict[str, Any]) -> str:
        location = player_state.get("current_location", {})
        parts = [
            str(location.get("region_id", "unknown location")),
            str(location.get("detail", "")).strip(),
        ]
        return " / ".join(part for part in parts if part)

    def _build_pressure_summary(self, session_state: GameSessionState) -> str:
        pressure = int(session_state.get("interruption_pressure", 0))
        if pressure <= 0:
            return "No active interruption pressure."
        if pressure == 1:
            return "The situation has mild urgency after one interrupted attempt."
        return f"The situation has rising urgency after {pressure} interrupted attempts."

    def _summarize_condition(self, status_effects: list[dict[str, Any]]) -> str:
        if not status_effects:
            return "No active status effects."
        return ", ".join(str(effect.get("name", effect.get("effect_id", "status"))) for effect in status_effects[:3])

    def _filter_relevant_rules(
        self,
        world_rules: dict[str, Any],
        attempted_action: str,
    ) -> list[str]:
        lowered_action = attempted_action.casefold()
        relevant_rules: list[str] = []
        for rule_group in ["hard_rules", "soft_rules", "meta_rules"]:
            for rule in world_rules.get(rule_group, []):
                searchable = " ".join(
                    str(rule.get(key, "")) for key in ["rule_id", "title", "description"]
                ).casefold()
                if any(word in searchable for word in lowered_action.split() if len(word) >= 4):
                    relevant_rules.append(f"{rule.get('title', rule.get('rule_id', 'rule'))}: {rule.get('description', '')}")
        return relevant_rules[:3]

    def _build_prechecked_blockers(
        self,
        entity_resolution: EntityResolutionResult,
    ) -> list[str]:
        if entity_resolution["execution_status"] == "clear":
            return []
        blockers = [
            f"unresolved_reference:{mention['source_text']}"
            for mention in entity_resolution["unresolved_mentions"]
        ]
        blockers.extend(
            f"ambiguous_reference:{mention['source_text']}"
            for mention in entity_resolution["ambiguous_mentions"]
        )
        if entity_resolution.get("resolver_status") == "suspicious_failure":
            blockers.append("suspicious_entity_resolution_failure")
        return blockers

    def _build_prechecked_warnings(
        self,
        entity_resolution: EntityResolutionResult,
        route_decision: RouteDecision,
    ) -> list[str]:
        warnings: list[str] = []
        plausible = [
            entity["source_text"]
            for entity in entity_resolution["resolved_entities"]
            if entity["truth_status"] == "plausible_contextual"
        ]
        if plausible:
            warnings.append(
                "plausible_contextual entities are not confirmed hard state: "
                + ", ".join(plausible)
            )
        if entity_resolution["execution_status"] == "clear" and (
            entity_resolution["unresolved_mentions"] or entity_resolution["ambiguous_mentions"]
        ):
            warnings.append(
                "optional unresolved or ambiguous references are not confirmed canonical entities"
            )
        if route_decision["action_category"] == "combat_attempt":
            warnings.append("combat mode is not implemented in this pipeline")
        return warnings

    def _build_confirmed_facts(
        self,
        entity_resolution: EntityResolutionResult,
        relevant_rules: list[str],
    ) -> list[str]:
        facts = [
            f"resolved:{entity['entity_type']}:{entity['entity_id']}:{entity['truth_status']}"
            for entity in entity_resolution["resolved_entities"]
        ]
        facts.extend(f"rule:{rule}" for rule in relevant_rules)
        return facts

    def _precondition_interruption(
        self,
        raw_player_input: str,
        expanded_player_intent: str,
        route_decision: RouteDecision,
        entity_resolution: EntityResolutionResult,
        session_state: GameSessionState,
    ) -> ActionProcessingContract:
        """Interrupt execution safely when required entity mentions are unresolved."""

        unresolved_text = [
            mention["source_text"] for mention in entity_resolution["unresolved_mentions"]
        ]
        ambiguous_text = [
            mention["source_text"] for mention in entity_resolution["ambiguous_mentions"]
        ]
        suspicious_failure = entity_resolution.get("resolver_status") == "suspicious_failure"
        pressure = max(0, int(session_state.get("interruption_pressure", 0)))
        blocker_text = []
        if unresolved_text:
            blocker_text.append(
                f"Unresolved references: {', '.join(unresolved_text)}."
            )
        if ambiguous_text:
            blocker_text.append(
                f"Ambiguous references: {', '.join(ambiguous_text)}."
            )
        if suspicious_failure:
            blocker_text.append("Entity references may have been missed; execution is paused for safety.")

        outcome_quality = clamp_outcome_quality(50 - (pressure * 5))
        risk_flags = ["interrupted_before_execution", "blocked_precondition"]
        if pressure >= 1:
            risk_flags.append("urgency_rising")
        if pressure >= 2:
            risk_flags.append("window_narrowing")

        side_effects: list[str] = []
        if pressure >= 1:
            side_effects.append("Repeated hesitation gives the situation more time to shift.")

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
            "outcome_quality": outcome_quality,
            "attempt_summary": "The attempt stalls before execution because a required reference cannot be confirmed.",
            "what_succeeds": [],
            "what_fails": ["The intended action cannot proceed until the referenced entity is clarified."],
            "blockers": blocker_text or ["A required entity reference could not be confirmed."],
            "side_effects": side_effects,
            "proposed_side_effects": side_effects,
            "applied_side_effects": [],
            "quality_side_effect_chance": 0.0,
            "quality_side_effect_applied": False,
            "revealed_information": [],
            "risk_flags": risk_flags,
            "state_intents": {
                "position_change": None,
                "entity_transfers": [],
                "skill_changes": [],
                "stat_changes": [],
                "currency_changes": [],
                "status_effect_changes": [],
                "resource_changes": {},
                "status_changes": [],
                "relationship_signals": [],
                "environment_changes": [],
            },
            "time_hints": {
                "duration_class": "instant",
                "effort_level": "low",
                "interrupted": True,
            },
            "reasoning_short": "Execution was interrupted before the action could begin because entity resolution stayed unresolved or ambiguous.",
            "outcome_summary": "",
            "applied_changes": [],
            "change_summary": [],
            "consequence_debug": {},
            "state_changes": [],
            "npc_reactions": [],
            "time_cost": {"amount": 0, "unit": "minute"},
            "narration_notes": [
                "Honor unresolved and ambiguous references as preconditions rather than confirmed facts.",
            ],
            "discovered_rule_candidate": None,
        }

    def _resolve_judge_output(
        self,
        llm_text: str,
        judge_input: ActionEvaluationInput,
        raw_player_input: str,
        expanded_player_intent: str,
        route_decision: RouteDecision,
    ) -> ActionProcessingContract:
        """Parse, validate, and repair Judge output where safe."""

        if llm_text.strip():
            logger.info("Judge structured output before parsing: %s", llm_text)
            try:
                parsed = self._parse_single_judge_object(llm_text)
                return self._validate_judge_output(
                    parsed=parsed,
                    raw_player_input=raw_player_input,
                    expanded_player_intent=expanded_player_intent,
                    route_decision=route_decision,
                    judge_input=judge_input,
                )
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.warning("Judge parse/validation failure: %s. Raw response: %s", exc, llm_text)
                repaired = self._repair_judge_output(
                    raw_response=llm_text,
                    judge_input=judge_input,
                    raw_player_input=raw_player_input,
                    expanded_player_intent=expanded_player_intent,
                    route_decision=route_decision,
                )
                if repaired is not None:
                    return repaired

        return self._blocked_fallback(
            raw_player_input=raw_player_input,
            expanded_player_intent=expanded_player_intent,
            route_decision=route_decision,
        )

    def _repair_judge_output(
        self,
        raw_response: str,
        judge_input: ActionEvaluationInput,
        raw_player_input: str,
        expanded_player_intent: str,
        route_decision: RouteDecision,
    ) -> ActionProcessingContract | None:
        """Retry once with a strict repair prompt when Judge output is malformed."""

        repair_prompt = (
            "Repair the malformed Judge response into exactly one valid JSON object.\n"
            "Use only the approved top-level fields from the schema.\n"
            "Remove forbidden fields, repeated objects, markdown, and prose.\n"
            "Return JSON only and stop after the final closing brace.\n\n"
            f"JUDGE_INPUT:\n{json.dumps(judge_input, ensure_ascii=False, indent=2)}\n\n"
            f"MALFORMED_RESPONSE:\n{raw_response}"
        )
        logger.info("Retrying Judge response repair. Repair payload size=%s chars", len(repair_prompt))
        self._dump_debug_file("judge_repair_prompt.txt", repair_prompt)
        repair_response = self._llm_adapter.generate_text(
            system_prompt=self._system_prompt,
            user_prompt=repair_prompt,
            format_json=True,
        )
        self._dump_debug_file("judge_repair_raw_response.txt", repair_response["text"])
        try:
            parsed = self._parse_single_judge_object(repair_response["text"])
            return self._validate_judge_output(
                parsed=parsed,
                raw_player_input=raw_player_input,
                expanded_player_intent=expanded_player_intent,
                route_decision=route_decision,
                judge_input=judge_input,
            )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Judge repair failed: %s. Raw repair response: %s", exc, repair_response["text"])
            return None

    def _parse_single_judge_object(self, raw_text: str) -> dict[str, Any]:
        """Parse exactly one JSON object and reject repeated or unknown-field output."""

        cleaned_text = self._normalize_json_text(raw_text)
        decoder = json.JSONDecoder()
        parsed, end_index = decoder.raw_decode(cleaned_text)
        if cleaned_text[end_index:].strip():
            raise ValueError("Judge returned extra content or repeated JSON after the first object.")
        if not isinstance(parsed, dict):
            raise TypeError("Judge response must be a JSON object.")

        unknown_fields = set(parsed) - APPROVED_JUDGE_FIELDS
        forbidden_fields = set(parsed) & FORBIDDEN_JUDGE_FIELDS
        if unknown_fields or forbidden_fields:
            raise ValueError(
                f"Judge returned unsupported fields: {sorted(unknown_fields | forbidden_fields)}"
            )
        return parsed

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
        judge_input: ActionEvaluationInput | None = None,
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
        if not state_intents["entity_transfers"] and judge_input is not None:
            state_intents["entity_transfers"] = self._infer_entity_transfers(judge_input)
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
            "proposed_side_effects": self._coerce_string_list(parsed.get("side_effects", [])),
            "applied_side_effects": [],
            "quality_side_effect_chance": 0.0,
            "quality_side_effect_applied": False,
            "revealed_information": self._coerce_string_list(parsed.get("revealed_information", [])),
            "risk_flags": self._coerce_string_list(parsed.get("risk_flags", [])),
            "state_intents": state_intents,
            "time_hints": time_hints,
            "reasoning_short": str(parsed.get("reasoning_short", "")).strip()
            or "Judge output repaired from incomplete model response.",
            "outcome_summary": "",
            "applied_changes": [],
            "change_summary": [],
            "consequence_debug": {},
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
            "entity_transfers": self._coerce_entity_transfers(data.get("entity_transfers", [])),
            "skill_changes": self._coerce_skill_changes(data.get("skill_changes", [])),
            "stat_changes": self._coerce_stat_changes(data.get("stat_changes", [])),
            "currency_changes": self._coerce_currency_changes(data.get("currency_changes", [])),
            "status_effect_changes": self._coerce_status_effect_changes(data.get("status_effect_changes", [])),
            "resource_changes": data.get("resource_changes", {}) if isinstance(data.get("resource_changes", {}), dict) else {},
            "status_changes": self._coerce_string_list(data.get("status_changes", [])),
            "relationship_signals": self._coerce_string_list(data.get("relationship_signals", [])),
            "environment_changes": self._coerce_string_list(data.get("environment_changes", [])),
        }

    def _coerce_entity_transfers(self, value: object) -> list[dict[str, Any]]:
        """Normalize Judge-proposed entity transfer intents."""

        if not isinstance(value, list):
            return []
        transfers: list[dict[str, Any]] = []
        valid_containers = {"scene_pool", "inventory", "equipped"}
        for entry in value:
            if not isinstance(entry, dict):
                continue
            entity_id = str(entry.get("entity_id", "")).strip()
            source = str(entry.get("from", "")).strip()
            target = str(entry.get("to", "")).strip()
            if not entity_id or source not in valid_containers or target not in valid_containers or source == target:
                continue
            try:
                quantity = max(1, int(entry.get("quantity", 1)))
            except (TypeError, ValueError):
                quantity = 1
            transfers.append(
                {
                    "entity_id": entity_id,
                    "entity_type": str(entry.get("entity_type", "")).strip() or "item",
                    "from": source,
                    "to": target,
                    "quantity": quantity,
                    "reason": str(entry.get("reason", "")).strip(),
                }
            )
        return transfers

    def _coerce_skill_changes(self, value: object) -> list[dict[str, Any]]:
        """Normalize Judge-proposed skill mutation intents."""

        if not isinstance(value, list):
            return []
        valid_ops = {"add", "remove", "level_up", "level_down", "set_level"}
        changes: list[dict[str, Any]] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            op = str(entry.get("op", "")).strip()
            skill_id = str(entry.get("skill_id", "")).strip()
            if op not in valid_ops or not skill_id:
                continue
            changes.append(
                {
                    "op": op,
                    "skill_id": skill_id,
                    "skill_data": entry.get("skill_data", {}) if isinstance(entry.get("skill_data", {}), dict) else {},
                    "amount": self._coerce_positive_number(entry.get("amount", 1)),
                    "new_value": self._coerce_optional_number(entry.get("new_value")),
                    "reason": str(entry.get("reason", "")).strip(),
                }
            )
        return changes

    def _coerce_stat_changes(self, value: object) -> list[dict[str, Any]]:
        """Normalize Judge-proposed stat mutation intents."""

        if not isinstance(value, list):
            return []
        valid_ops = {"increase", "decrease", "set"}
        changes: list[dict[str, Any]] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            op = str(entry.get("op", "")).strip()
            stat_id = str(entry.get("stat_id", "")).strip()
            if op not in valid_ops or not stat_id:
                continue
            changes.append(
                {
                    "op": op,
                    "stat_id": stat_id,
                    "amount": self._coerce_positive_number(entry.get("amount", 1)),
                    "new_value": self._coerce_optional_number(entry.get("new_value")),
                    "reason": str(entry.get("reason", "")).strip(),
                }
            )
        return changes

    def _coerce_currency_changes(self, value: object) -> list[dict[str, Any]]:
        """Normalize Judge-proposed currency mutation intents."""

        if not isinstance(value, list):
            return []
        valid_ops = {"add", "spend", "set"}
        changes: list[dict[str, Any]] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            op = str(entry.get("op", "")).strip()
            currency_id = str(entry.get("currency_id", "")).strip()
            if op not in valid_ops or not currency_id:
                continue
            changes.append(
                {
                    "op": op,
                    "currency_id": currency_id,
                    "amount": self._coerce_positive_number(entry.get("amount", 1)),
                    "currency_data": entry.get("currency_data", {}) if isinstance(entry.get("currency_data", {}), dict) else {},
                    "reason": str(entry.get("reason", "")).strip(),
                }
            )
        return changes

    def _coerce_status_effect_changes(self, value: object) -> list[dict[str, Any]]:
        """Normalize Judge-proposed status-effect mutation intents."""

        if not isinstance(value, list):
            return []
        valid_ops = {"add", "remove", "refresh"}
        changes: list[dict[str, Any]] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            op = str(entry.get("op", "")).strip()
            effect_id = str(entry.get("effect_id", "")).strip()
            if op not in valid_ops or not effect_id:
                continue
            changes.append(
                {
                    "op": op,
                    "effect_id": effect_id,
                    "effect_data": entry.get("effect_data", {}) if isinstance(entry.get("effect_data", {}), dict) else {},
                    "duration": self._coerce_optional_number(entry.get("duration")),
                    "reason": str(entry.get("reason", "")).strip(),
                }
            )
        return changes

    def _coerce_positive_number(self, value: object) -> int | float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 1
        number = max(1, number)
        return int(number) if number.is_integer() else number

    def _coerce_optional_number(self, value: object) -> int | float | None:
        if value in {None, ""}:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return int(number) if number.is_integer() else number

    def _infer_entity_transfers(self, judge_input: ActionEvaluationInput) -> list[dict[str, Any]]:
        """Conservatively infer simple transfer intents when Judge omits the field."""

        entity_resolution = judge_input.get("entity_resolution", {})
        resolved_entities = entity_resolution.get("resolved_entities", [])
        if not isinstance(resolved_entities, list) or not resolved_entities:
            return []

        transfer_text = " ".join(
            [
                judge_input.get("raw_player_input", ""),
                judge_input.get("attempted_action", ""),
                judge_input.get("attempted_method", ""),
                judge_input.get("primary_intent", ""),
            ]
        ).casefold()
        for entity in resolved_entities:
            if not isinstance(entity, dict):
                continue
            source = self._container_from_resolved_entity(entity)
            target = self._infer_transfer_target(transfer_text, source)
            if not source or not target:
                continue
            entity_type = str(entity.get("entity_type", "item"))
            if entity_type in {"actor", "currency", "skill"}:
                continue
            return [
                {
                    "entity_id": str(entity.get("entity_id", "")).strip(),
                    "entity_type": entity_type,
                    "from": source,
                    "to": target,
                    "quantity": 1,
                    "reason": "Inferred simple entity transfer from routed action and resolved entity.",
                }
            ]
        return []

    def _container_from_resolved_entity(self, entity: dict[str, Any]) -> str:
        source = str(entity.get("candidate_source", "")).strip()
        truth_status = str(entity.get("truth_status", "")).strip()
        if source in {"held", "equipment"}:
            return "equipped"
        if source == "inventory":
            return "inventory"
        if source == "scene_pool" or truth_status == "soft_scene":
            return "scene_pool"
        return ""

    def _infer_transfer_target(self, text: str, source: str) -> str:
        take_terms = ["pick up", "take", "grab", "collect", "підня", "взя", "забра"]
        drop_terms = ["drop", "leave", "put down", "discard", "кину", "залиш", "покла"]
        equip_terms = ["equip", "hold", "ready", "wear", "діста", "трима", "вдяг", "озбро"]
        unequip_terms = ["put away", "unequip", "stow", "прибра", "схова"]
        if source == "scene_pool" and any(term in text for term in equip_terms):
            return "equipped"
        if source == "scene_pool" and any(term in text for term in take_terms):
            return "inventory"
        if source == "inventory" and any(term in text for term in equip_terms):
            return "equipped"
        if source == "inventory" and any(term in text for term in drop_terms):
            return "scene_pool"
        if source == "equipped" and any(term in text for term in unequip_terms):
            return "inventory"
        if source == "equipped" and any(term in text for term in drop_terms):
            return "scene_pool"
        return ""

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
            "proposed_side_effects": [],
            "applied_side_effects": [],
            "quality_side_effect_chance": 0.0,
            "quality_side_effect_applied": False,
            "revealed_information": [],
            "risk_flags": [],
            "state_intents": {
                "position_change": None,
                "entity_transfers": [],
                "skill_changes": [],
                "stat_changes": [],
                "currency_changes": [],
                "status_effect_changes": [],
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
            "applied_changes": [],
            "change_summary": [],
            "consequence_debug": {},
            "state_changes": [],
            "npc_reactions": [],
            "time_cost": {"amount": 0, "unit": "minute"},
            "narration_notes": [],
            "discovered_rule_candidate": None,
        }

    def _dump_debug_file(self, file_name: str, content: str) -> None:
        """Optionally write exact Judge payloads for local debugging."""

        if os.getenv("JUDGE_DEBUG_DUMP", "false").lower() != "true":
            return
        try:
            DEBUG_DUMP_DIR.mkdir(parents=True, exist_ok=True)
            (DEBUG_DUMP_DIR / file_name).write_text(content, encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not write Judge debug dump %s: %s", file_name, exc)
