"""Presentation-only narrator for player-facing exploration text."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import re
from typing import Any

from backend.modules.action_evaluation.schemas.action_evaluation_contracts import (
    ActionProcessingContract,
)
from backend.modules.llm_connector.services.llm_client import LLMAdapter
from backend.modules.router.schemas.router_contracts import RouteDecision


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "narration.txt"
AVAILABLE_ENTITY_PATTERN = re.compile(r"\[\[scene_entity:available\|([^\]]+)\]\]")


class NarratorService:
    """Render player-facing narration without making gameplay decisions."""

    def __init__(self, llm_adapter: LLMAdapter) -> None:
        self._llm_adapter = llm_adapter
        self._system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def render_narrative(
        self,
        action_result: ActionProcessingContract,
        visible_state: dict,
        route_decision: RouteDecision,
        output_language: str = "uk",
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Convert a structured action result into a short narrative response."""

        narration_context = build_narration_context(
            action_result=action_result,
            visible_state=visible_state,
            route_decision=route_decision,
            output_language=output_language,
        )
        user_prompt = json.dumps(narration_context, ensure_ascii=False, indent=2)
        raw_text = self._generate_narrator_text(user_prompt, on_token=on_token)
        text = sanitize_narrator_output(raw_text)
        if text:
            return text
        return self._render_fallback_narrative(narration_context)

    def _generate_narrator_text(
        self,
        user_prompt: str,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Stream narrator output when requested, while accumulating full text."""

        if on_token is not None and hasattr(self._llm_adapter, "stream_text"):
            chunks: list[str] = []
            for chunk in self._llm_adapter.stream_text(
                system_prompt=self._system_prompt,
                user_prompt=user_prompt,
            ):
                chunks.append(chunk)
                on_token(chunk)
            return "".join(chunks)

        llm_response = self._llm_adapter.generate_text(
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
        )
        return str(llm_response.get("text", "")).strip()

    def _render_fallback_narrative(self, narration_context: dict[str, Any]) -> str:
        """Fallback narration used when the local LLM is unavailable."""

        result = narration_context["result"]
        fragments = [result.get("summary") or result.get("attempt_summary") or ""]

        if result.get("action_result") == "blocked" and result.get("blockers"):
            fragments.append(f"Blocked: {result['blockers'][0]}.")
        elif result.get("what_succeeds"):
            fragments.append(str(result["what_succeeds"][0]))
        elif result.get("what_fails"):
            fragments.append(str(result["what_fails"][0]))

        if result.get("revealed_information"):
            fragments.append(str(result["revealed_information"][0]))
        if narration_context.get("npc_reactions"):
            fragments.append(str(narration_context["npc_reactions"][0].get("summary", "")))
        return " ".join(fragment for fragment in fragments if fragment).strip()


def build_narration_context(
    action_result: dict[str, Any],
    visible_state: dict[str, Any],
    route_decision: dict[str, Any],
    output_language: str,
) -> dict[str, Any]:
    """Build the v1 narrator contract from existing action/pipeline fields."""

    player = visible_state.get("player", {}) if isinstance(visible_state, dict) else {}
    location = player.get("current_location", {}) if isinstance(player, dict) else {}
    summary = (
        str(action_result.get("outcome_summary", "")).strip()
        or str(action_result.get("attempt_summary", "")).strip()
        or str(action_result.get("reasoning_short", "")).strip()
    )
    return {
        "output_language": output_language or "uk",
        "raw_player_input": str(action_result.get("raw_player_input", "")),
        "expanded_player_intent": str(action_result.get("expanded_player_intent", "")),
        "result": {
            "action_result": str(action_result.get("action_result", "")),
            "outcome_quality": int(action_result.get("outcome_quality", 0) or 0),
            "summary": summary,
            "attempt_summary": str(action_result.get("attempt_summary", "")),
            "what_succeeds": _safe_list(action_result.get("what_succeeds", [])),
            "what_fails": _safe_list(action_result.get("what_fails", [])),
            "blockers": _safe_list(action_result.get("blockers", [])),
            "revealed_information": _safe_list(action_result.get("revealed_information", [])),
            "side_effects": _safe_list(action_result.get("applied_side_effects", action_result.get("side_effects", []))),
        },
        "scene": {
            "location": _format_location(location),
            "description_hints": str(route_decision.get("primary_intent", "")),
        },
        "npc_reactions": _safe_list(action_result.get("npc_reactions", [])),
        "narration_notes": _safe_list(action_result.get("narration_notes", [])),
    }


def detect_output_language(raw_input: str, fallback: str = "uk") -> str:
    """Detect the session narration language from the first player message."""

    text = raw_input.strip()
    if not text:
        return fallback
    if any(character in text.casefold() for character in ["і", "ї", "є", "ґ"]):
        return "uk"
    cyrillic_count = len(re.findall(r"[А-Яа-яЁёІіЇїЄєҐґ]", text))
    latin_count = len(re.findall(r"[A-Za-z]", text))
    if cyrillic_count > latin_count:
        return "uk"
    if latin_count > cyrillic_count:
        return "en"
    return fallback


def sanitize_narrator_output(raw_text: str) -> str:
    """Normalize bad narrator formats without damaging valid entity markers."""

    cleaned = raw_text.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()
        if cleaned.lower().startswith(("json", "text")):
            cleaned = cleaned.split("\n", 1)[1].strip() if "\n" in cleaned else ""

    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return cleaned

    if isinstance(parsed, str):
        return parsed.strip()
    if isinstance(parsed, dict):
        for key in ["text", "narration", "content", "response"]:
            value = parsed.get(key)
            if isinstance(value, str):
                return value.strip()
    return cleaned


def extract_available_entities(narrative_text: str) -> list[dict[str, str]]:
    """Extract v1 available scene entity markers from final narrator text."""

    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in AVAILABLE_ENTITY_PATTERN.finditer(narrative_text):
        name = match.group(1).strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        candidates.append({"name": name, "source": "narrator", "status": "candidate"})
    return candidates


def store_scene_candidates(session_state: dict[str, Any], candidates: list[dict[str, str]]) -> None:
    """Store narrator-produced available scene entity candidates for this session."""

    if not candidates:
        return
    existing = session_state.setdefault("available_scene_entities", [])
    seen = {str(candidate.get("name", "")).strip().casefold() for candidate in existing}
    for candidate in candidates:
        key = candidate["name"].strip().casefold()
        if key in seen:
            continue
        seen.add(key)
        existing.append(candidate)


def _safe_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _format_location(location: object) -> str:
    if not isinstance(location, dict):
        return ""
    parts = [
        str(location.get("region_id", "")).strip(),
        str(location.get("detail", "")).strip(),
    ]
    return " / ".join(part for part in parts if part)
