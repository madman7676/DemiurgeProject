"""Narrator v1 contract checks."""

from __future__ import annotations

import json
import unittest

from backend.core.game_state.services.exploration_pipeline import ExplorationPipeline
from backend.core.game_state.services.session_service import InMemorySessionStore
from backend.modules.narrator.services.narrator_service import (
    NarratorService,
    build_narration_context,
    detect_output_language,
    extract_available_entities,
    sanitize_narrator_output,
    store_scene_candidates,
)


class FakeNarratorLLM:
    def __init__(self, text: str = "", chunks: list[str] | None = None) -> None:
        self.text = text
        self.chunks = chunks or []
        self.stream_calls = 0

    def generate_text(self, system_prompt: str, user_prompt: str, format_json: bool = False) -> dict:
        return {"text": self.text, "provider": "test", "model": "fake", "used_mock": False}

    def stream_text(self, system_prompt: str, user_prompt: str, format_json: bool = False):
        self.stream_calls += 1
        yield from self.chunks


def _action_result(**overrides):
    base = {
        "action_type": "inspection",
        "raw_player_input": "оглянутись",
        "expanded_player_intent": "look around",
        "interpreted_intent": {"primary_goal": "inspect", "target_ids": [], "approach": "inspection", "notes": []},
        "action_result": "success",
        "outcome_quality": 55,
        "attempt_summary": "The actor looks around.",
        "what_succeeds": ["The actor observes the area."],
        "what_fails": [],
        "blockers": [],
        "side_effects": [],
        "proposed_side_effects": [],
        "applied_side_effects": [],
        "quality_side_effect_chance": 0.0,
        "quality_side_effect_applied": False,
        "revealed_information": [],
        "risk_flags": [],
        "state_intents": {
            "position_change": None,
            "resource_changes": {},
            "status_changes": [],
            "relationship_signals": [],
            "environment_changes": [],
        },
        "time_hints": {"duration_class": "short", "effort_level": "low", "interrupted": False},
        "reasoning_short": "Looking around is possible.",
        "outcome_summary": "",
        "state_changes": [],
        "npc_reactions": [],
        "time_cost": {"amount": 1, "unit": "minute"},
        "narration_notes": [],
        "discovered_rule_candidate": None,
    }
    base.update(overrides)
    return base


class NarratorV1Tests(unittest.TestCase):
    def test_build_narration_context_uses_existing_fallback_fields(self) -> None:
        context = build_narration_context(
            action_result={"attempt_summary": "Attempt summary.", "what_succeeds": ["Done."]},
            visible_state={"player": {"current_location": {"region_id": "market", "detail": "crossroads"}}},
            route_decision={"primary_intent": "inspect"},
            output_language="uk",
        )
        self.assertEqual(context["result"]["summary"], "Attempt summary.")
        self.assertEqual(context["scene"]["location"], "market / crossroads")

    def test_language_detection(self) -> None:
        self.assertEqual(detect_output_language("оглянутись"), "uk")
        self.assertEqual(detect_output_language("look around"), "en")
        self.assertEqual(detect_output_language("", fallback="uk"), "uk")

    def test_sanitize_json_and_markers_without_stripping_markers(self) -> None:
        text = sanitize_narrator_output(
            json.dumps({"text": "Ти бачиш [[scene_entity:available|кам'яний колодязь]]."})
        )
        self.assertIn("[[scene_entity:available|кам'яний колодязь]]", text)
        self.assertEqual(sanitize_narrator_output('"plain text"'), "plain text")

    def test_extracts_only_available_scene_entities(self) -> None:
        candidates = extract_available_entities(
            "[[scene_entity:available|криниця]] і [[scene_entity:background|хмари]] біля [[reference:known_reference|міста]]."
        )
        self.assertEqual(candidates, [{"name": "криниця", "source": "narrator", "status": "candidate"}])

    def test_store_scene_candidates_dedupes(self) -> None:
        session_state = {"available_scene_entities": [{"name": "Криниця", "source": "narrator", "status": "candidate"}]}
        store_scene_candidates(
            session_state,
            [
                {"name": "криниця", "source": "narrator", "status": "candidate"},
                {"name": "камінь", "source": "narrator", "status": "candidate"},
            ],
        )
        self.assertEqual(len(session_state["available_scene_entities"]), 2)

    def test_narrator_streams_and_sanitizes_after_full_text(self) -> None:
        adapter = FakeNarratorLLM(chunks=["```json\n{\"text\":\"Ти бачиш ", "[[scene_entity:available|криниця]].\"}\n```"])
        service = NarratorService(llm_adapter=adapter)
        chunks: list[str] = []
        text = service.render_narrative(
            action_result=_action_result(),
            visible_state={"player": {"current_location": {"region_id": "market"}}},
            route_decision={"primary_intent": "inspect", "action_category": "inspection"},
            output_language="uk",
            on_token=chunks.append,
        )
        self.assertEqual(adapter.stream_calls, 1)
        self.assertEqual(text, "Ти бачиш [[scene_entity:available|криниця]].")
        self.assertTrue(chunks)

    def test_pipeline_sets_language_once_and_stores_narrator_candidates(self) -> None:
        session_store = InMemorySessionStore()
        pipeline = ExplorationPipeline(
            session_store=session_store,
            router_service=_RouterStub(),
            entity_resolver_service=_ResolverStub(),
            action_evaluation_service=_ActionStub(),
            narrator_service=_NarratorStub(),
        )
        pipeline.process_player_message("оглянутись")
        pipeline.process_player_message("look around")
        session_state = session_store.get_session()
        self.assertEqual(session_state["output_language"], "uk")
        self.assertEqual(
            session_state["available_scene_entities"],
            [{"name": "криниця", "source": "narrator", "status": "candidate"}],
        )

    def test_pipeline_emits_current_step_statuses(self) -> None:
        session_store = InMemorySessionStore()
        pipeline = ExplorationPipeline(
            session_store=session_store,
            router_service=_RouterStub(),
            entity_resolver_service=_ResolverStub(),
            action_evaluation_service=_ActionStub(),
            narrator_service=_NarratorStub(),
        )
        statuses: list[str] = []

        pipeline.process_player_message("оглянутись", on_status=statuses.append)

        self.assertEqual(
            statuses,
            ["router", "judge", "time", "consequence", "narrator"],
        )

    def test_pipeline_emits_progressive_step_updates(self) -> None:
        session_store = InMemorySessionStore()
        pipeline = ExplorationPipeline(
            session_store=session_store,
            router_service=_RouterStub(),
            entity_resolver_service=_ResolverStub(),
            action_evaluation_service=_ActionStub(),
            narrator_service=_NarratorStub(),
        )
        updates: list[dict] = []

        pipeline.process_player_message("оглянутись", on_pipeline_update=updates.append)

        self.assertEqual(
            [update["step"] for update in updates],
            ["router", "entity_resolver", "judge", "narrator"],
        )
        self.assertEqual(updates[1]["user_message"]["annotations"], [])
        self.assertEqual(updates[-1]["narrative_text"], "Ти бачиш [[scene_entity:available|криниця]].")
        self.assertTrue(updates[-1]["decision_events"])


class _RouterStub:
    def route_message(self, router_input: dict) -> dict:
        return {
            "action_category": "inspection",
            "expanded_player_intent": "look around",
            "primary_intent": "inspect surroundings",
            "secondary_elements": [],
            "possible_targets": [],
            "requested_agents": [],
            "narration_notes": [],
            "routing_reason": "test",
            "entity_resolution_hint": {"needed": False, "reason": "test"},
        }


class _ResolverStub:
    def resolve_entities(self, raw_player_input: str, route_decision: dict, session_state: dict) -> dict:
        return {
            "raw_input": raw_player_input,
            "resolved_entities": [],
            "unresolved_mentions": [],
            "ambiguous_mentions": [],
            "annotations": [],
            "execution_status": "clear",
            "resolver_status": "clear",
            "debug": {
                "candidate_count": 0,
                "candidate_sources_used": [],
                "matches_considered": [],
                "semantic_resolver": {},
                "resolver_status": "clear",
            },
        }

    def refresh_scene_entity_pool(self, **kwargs) -> None:
        return None


class _ActionStub:
    def evaluate_action(self, raw_player_input: str, route_decision: dict, entity_resolution: dict, session_state: dict) -> dict:
        return _action_result(raw_player_input=raw_player_input)


class _NarratorStub:
    def __init__(self) -> None:
        self.languages: list[str] = []

    def render_narrative(self, action_result: dict, visible_state: dict, route_decision: dict, output_language: str = "uk", on_token=None) -> str:
        self.languages.append(output_language)
        return "Ти бачиш [[scene_entity:available|криниця]]."


if __name__ == "__main__":
    unittest.main()
