"""Coordinates which backend modules should process a player action."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.modules.llm_connector.services.llm_client import LLMAdapter
from backend.modules.router.schemas.router_contracts import (
    RouteDecision,
    RouterAgentInput,
)


logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "router_agent.txt"


class RouterService:
    """LLM-driven Router Agent with a small deterministic fallback."""

    def __init__(self, llm_adapter: LLMAdapter) -> None:
        self._llm_adapter = llm_adapter
        self._system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def route_message(self, router_input: RouterAgentInput) -> RouteDecision:
        """Route a player message into normalized intent plus optional module requests."""

        raw_player_input = router_input["raw_player_input"]
        logger.info("Router Agent raw player input: %s", raw_player_input)
        user_prompt = self._build_user_prompt(router_input)
        logger.debug("Router Agent formatted input:\n%s", user_prompt)
        llm_response = self._llm_adapter.generate_text(
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
        )

        if llm_response["text"].strip():
            logger.info("Router Agent structured output before parsing: %s", llm_response["text"])
            try:
                cleaned_text = self._normalize_json_text(llm_response["text"])
                parsed = json.loads(cleaned_text)
                route_decision = self._coerce_route_decision(parsed, router_input)
                self._log_route_decision("Router Agent decision", route_decision)
                return route_decision
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                logger.warning(
                    "Router Agent parse failure. Raw response: %s",
                    llm_response["text"],
                )

        route_decision = self._fallback_route(router_input)
        self._log_route_decision("Router Agent fallback", route_decision)
        return route_decision

    def _build_user_prompt(self, router_input: RouterAgentInput) -> str:
        """Build a structured Router Agent prompt with clear priority ordering."""

        sections = [
            self._format_section(
                "TASK",
                [
                    "Determine the player's main intent for this turn.",
                    "Treat RAW_PLAYER_INPUT as the primary source of intent.",
                    "Use supporting context only to resolve ambiguity, never to override the player's message.",
                ],
            ),
            self._format_section("RAW_PLAYER_INPUT", router_input["raw_player_input"]),
            self._format_section("GAME_MODE", router_input["game_mode"]),
            self._format_section(
                "SCENE_CONTEXT",
                router_input["scene_context"],
            ),
            self._format_section(
                "VISIBLE_ENTITIES",
                {
                    "priority_note": (
                        "Use only as disambiguation aid. Do not assume the player targets "
                        "a visible entity unless the player's message suggests it."
                    ),
                    "entities": router_input["visible_entities_summary"],
                },
            ),
            self._format_section("AVAILABLE_MODULES", router_input["available_modules"]),
            self._format_section(
                "LAST_PRESENTED_CHOICES",
                {
                    "priority_note": (
                        "Only use this section if the player input appears to select a prior "
                        "choice directly or with extra clarification."
                    ),
                    "choices": router_input["last_presented_choices"],
                },
            ),
            self._format_section("ACTIVE_FEATURES", router_input["active_features"]),
            self._format_section(
                "OUTPUT_REQUIREMENTS",
                [
                    "Return strict raw JSON only.",
                    "Do not use markdown or code fences.",
                    "Do not add explanations outside JSON.",
                    "Keep raw_player_input intent primary and context secondary.",
                ],
            ),
        ]
        return "\n\n".join(sections)

    def _format_section(self, title: str, content: object) -> str:
        """Format one labeled Router Agent prompt section."""

        if isinstance(content, list):
            if not content:
                body = "[]"
            elif all(isinstance(item, str) for item in content):
                body = "\n".join(f"- {item}" for item in content)
            else:
                body = json.dumps(content, ensure_ascii=False, indent=2)
        elif isinstance(content, dict):
            body = json.dumps(content, ensure_ascii=False, indent=2)
        else:
            body = str(content)
        return f"{title}\n{body}"

    def _normalize_json_text(self, raw_text: str) -> str:
        """Normalize Router Agent JSON output before parsing."""

        cleaned = raw_text.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            logger.info("Removed markdown code fences from Router Agent response.")
            cleaned = cleaned[3:-3].strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        return cleaned

    def _coerce_route_decision(
        self,
        parsed: dict,
        router_input: RouterAgentInput,
    ) -> RouteDecision:
        """Coerce parsed LLM output into the Router Agent contract."""

        requested_agent_candidates = self._safe_string_list(
            parsed.get("requested_agents", []),
        )
        requested_agents = [
            module_name
            for module_name in requested_agent_candidates
            if module_name in router_input["available_modules"]
        ]
        action_category = parsed.get("action_category", "inspection")
        if action_category not in {
            "speech",
            "inspection",
            "movement",
            "question",
            "idle",
            "combat_attempt",
        }:
            action_category = "inspection"

        expanded_player_intent = str(parsed.get("expanded_player_intent", "")).strip()
        if not expanded_player_intent:
            raise ValueError("expanded_player_intent is required")

        return {
            "action_category": action_category,
            "expanded_player_intent": expanded_player_intent,
            "primary_intent": str(parsed.get("primary_intent", expanded_player_intent)).strip(),
            "secondary_elements": self._safe_string_list(parsed.get("secondary_elements", [])),
            "possible_targets": self._safe_string_list(parsed.get("possible_targets", [])),
            "requested_agents": requested_agents,
            "narration_notes": self._safe_string_list(parsed.get("narration_notes", [])),
            "routing_reason": str(parsed.get("routing_reason", "Router Agent selected this route.")).strip(),
        }

    def _safe_string_list(self, value: object) -> list[str]:
        """Normalize a possible string list into clean text items."""

        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _log_route_decision(self, prefix: str, route_decision: RouteDecision) -> None:
        """Log the full Router Agent decision in a readable structured format."""

        logger.info(
            (
                "%s:\n"
                "  action_category=%s\n"
                "  expanded_player_intent=%s\n"
                "  primary_intent=%s\n"
                "  secondary_elements=%s\n"
                "  possible_targets=%s\n"
                "  requested_agents=%s\n"
                "  narration_notes=%s\n"
                "  routing_reason=%s"
            ),
            prefix,
            route_decision["action_category"],
            route_decision["expanded_player_intent"],
            route_decision["primary_intent"],
            route_decision["secondary_elements"],
            route_decision["possible_targets"],
            route_decision["requested_agents"],
            route_decision["narration_notes"],
            route_decision["routing_reason"],
        )

    def _fallback_route(self, router_input: RouterAgentInput) -> RouteDecision:
        """Fallback router behavior when LLM output is unavailable or invalid."""

        expanded_intent = self._expand_quick_choice(router_input)
        lowered = expanded_intent.lower()

        if any(keyword in lowered for keyword in ["attack", "fight", "kill", "stab", "shoot"]):
            action_category = "combat_attempt"
            primary_intent = "attempt combat"
            routing_reason = "Fallback routing detected combat language."
        elif lowered.endswith("?") or any(
            lowered.startswith(prefix)
            for prefix in ["what ", "who ", "where ", "when ", "why ", "how ", "ask "]
        ):
            action_category = "question"
            primary_intent = "ask for information"
            routing_reason = "Fallback routing detected a question."
        elif any(
            keyword in lowered
            for keyword in ["go ", "walk", "move", "travel", "head to", "north", "south", "east", "west"]
        ):
            action_category = "movement"
            primary_intent = "move through the area"
            routing_reason = "Fallback routing detected movement language."
        elif any(keyword in lowered for keyword in ["say", "speak", "talk", "hello", "greet"]):
            action_category = "speech"
            primary_intent = "speak to someone nearby"
            routing_reason = "Fallback routing detected speech."
        elif any(keyword in lowered for keyword in ["wait", "rest", "pause", "hesitate", "think"]):
            action_category = "idle"
            primary_intent = "let time pass"
            routing_reason = "Fallback routing detected idle intent."
        else:
            action_category = "inspection"
            primary_intent = "inspect the current situation"
            routing_reason = "Fallback routing defaulted to inspection."

        possible_targets = [
            entity["name"]
            for entity in router_input["visible_entities_summary"]
            if entity["name"].lower() in expanded_intent.lower()
        ]
        requested_agents = []
        if "npc_reaction" in router_input["available_modules"] and action_category in {"speech", "question"}:
            requested_agents.append("npc_reaction")

        return {
            "action_category": action_category,
            "expanded_player_intent": expanded_intent,
            "primary_intent": primary_intent,
            "secondary_elements": [],
            "possible_targets": possible_targets,
            "requested_agents": requested_agents,
            "narration_notes": [],
            "routing_reason": routing_reason,
        }

    def _expand_quick_choice(self, router_input: RouterAgentInput) -> str:
        """Expand a quick-choice reference into a normal intent string when possible."""

        raw_text = router_input["raw_player_input"].strip()
        lowered = raw_text.lower()

        for choice in router_input["last_presented_choices"]:
            choice_id = choice["choice_id"].lower()
            label = choice["label"].lower()

            if lowered == choice_id or lowered == label:
                return choice["intent_text"]

            if lowered.startswith(choice_id) and self._has_choice_separator(
                raw_text[len(choice["choice_id"]) :],
            ):
                clarification = raw_text[len(choice["choice_id"]) :].lstrip(" ,:-")
                return f"{choice['intent_text']} {clarification}".strip()

            if lowered.startswith(label) and self._has_choice_separator(
                raw_text[len(choice["label"]) :],
            ):
                clarification = raw_text[len(choice["label"]) :].lstrip(" ,:-")
                return f"{choice['intent_text']} {clarification}".strip()

        return raw_text

    def _has_choice_separator(self, remaining_text: str) -> bool:
        """Check whether the remaining quick-choice text begins like clarification."""

        return not remaining_text or remaining_text[:1] in {" ", ",", ":", "-"}
