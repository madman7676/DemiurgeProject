"""Lightweight checks for Judge input shaping and quality-based side effects."""

from __future__ import annotations

import json
import unittest
from random import Random

from backend.core.game_state.services.quality_side_effects import (
    quality_side_effect_chance,
    should_apply_quality_side_effect,
)
from backend.core.game_state.services.session_service import create_initial_session_state
from backend.modules.action_evaluation.services.action_evaluation_service import (
    ActionEvaluationService,
)
from backend.modules.entity_resolver.schemas.entity_resolver_contracts import (
    EntityResolutionResult,
)


class _FakeLLMAdapter:
    """Small stub that returns deterministic Judge JSON."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.calls: list[dict[str, object]] = []

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        format_json: bool = False,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "format_json": format_json,
            }
        )
        return {
            "text": json.dumps(self._payload),
            "provider": "test",
            "model": "stub",
            "used_mock": True,
        }


class _SequenceLLMAdapter:
    """Stub that returns raw text responses in order."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls: list[dict[str, object]] = []

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        format_json: bool = False,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "format_json": format_json,
            }
        )
        text = self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]
        return {
            "text": text,
            "provider": "test",
            "model": "stub",
            "used_mock": True,
        }


class QualitySideEffectTests(unittest.TestCase):
    """Validate deterministic chance shaping around Judge outcome quality."""

    def test_neutral_quality_has_zero_chance(self) -> None:
        self.assertEqual(quality_side_effect_chance(50), 0.0)
        self.assertFalse(should_apply_quality_side_effect(50, rng=Random(0)))

    def test_positive_quality_edges_are_symmetric(self) -> None:
        self.assertAlmostEqual(quality_side_effect_chance(61), 0.025)
        self.assertEqual(quality_side_effect_chance(80), 0.5)
        self.assertEqual(quality_side_effect_chance(100), 1.0)

    def test_negative_quality_edges_are_symmetric(self) -> None:
        self.assertAlmostEqual(quality_side_effect_chance(40), 0.025)
        self.assertAlmostEqual(quality_side_effect_chance(20), 21 / 40)
        self.assertEqual(quality_side_effect_chance(0), 1.0)

    def test_extremes_always_apply(self) -> None:
        self.assertTrue(should_apply_quality_side_effect(100, rng=Random(999)))
        self.assertTrue(should_apply_quality_side_effect(0, rng=Random(999)))


class ActionEvaluationInputTests(unittest.TestCase):
    """Ensure actor-style Judge input remains safe with incomplete state."""

    def test_missing_acting_character_fields_do_not_crash(self) -> None:
        session_state = create_initial_session_state()
        session_state["player_state"].pop("inventory", None)
        session_state["player_state"].pop("stats", None)
        session_state["player_state"].pop("skills", None)
        session_state["player_state"].pop("background", None)
        session_state["player_state"]["identity"] = {}

        fake_adapter = _FakeLLMAdapter(
            {
                "action_result": "success",
                "outcome_quality": 50,
                "attempt_summary": "The actor inspects the area carefully.",
                "what_succeeds": ["A quick scan of the scene succeeds."],
                "what_fails": [],
                "blockers": [],
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
                    "effort_level": "low",
                    "interrupted": False,
                },
                "reasoning_short": "Baseline actor context is still enough for a safe evaluation.",
            }
        )
        service = ActionEvaluationService(llm_adapter=fake_adapter)

        route_decision = {
            "action_category": "inspection",
            "expanded_player_intent": "look around the area",
            "primary_intent": "inspect surroundings",
            "secondary_elements": [],
            "possible_targets": [],
            "requested_agents": [],
            "narration_notes": [],
            "routing_reason": "Inspection intent is explicit.",
        }
        entity_resolution: EntityResolutionResult = {
            "raw_input": "look around",
            "resolved_entities": [],
            "unresolved_mentions": [],
            "ambiguous_mentions": [],
            "annotations": [],
            "execution_status": "clear",
            "debug": {
                "candidate_count": 0,
                "candidate_sources_used": [],
                "matches_considered": [],
            },
        }

        result = service.evaluate_action(
            raw_player_input="look around",
            route_decision=route_decision,
            entity_resolution=entity_resolution,
            session_state=session_state,
        )

        self.assertEqual(result["expanded_player_intent"], "look around the area")
        self.assertEqual(result["outcome_quality"], 50)
        self.assertEqual(result["proposed_side_effects"], [])
        self.assertEqual(result["applied_side_effects"], [])
        judge_input = json.loads(fake_adapter.calls[0]["user_prompt"])
        self.assertIn("acting_character", judge_input)
        self.assertIn("prechecked_facts", judge_input)
        self.assertNotIn("player_state", judge_input)
        self.assertNotIn("inventory", judge_input)
        self.assertTrue(fake_adapter.calls[0]["format_json"])

    def test_repeated_or_forbidden_judge_output_is_repaired_once(self) -> None:
        session_state = create_initial_session_state()
        route_decision = {
            "action_category": "inspection",
            "expanded_player_intent": "look around",
            "primary_intent": "inspect surroundings",
            "secondary_elements": [],
            "possible_targets": [],
            "requested_agents": [],
            "narration_notes": [],
            "routing_reason": "Inspection intent is explicit.",
        }
        entity_resolution: EntityResolutionResult = {
            "raw_input": "look around",
            "resolved_entities": [],
            "unresolved_mentions": [],
            "ambiguous_mentions": [],
            "annotations": [],
            "execution_status": "clear",
            "debug": {
                "candidate_count": 0,
                "candidate_sources_used": [],
                "matches_considered": [],
            },
        }
        bad_response = (
            '{"action_result":"success","outcome_quality":55,"description":"too much"}'
            '{"action_result":"success","outcome_quality":55}'
        )
        repaired_response = json.dumps(
            {
                "action_result": "success",
                "outcome_quality": 55,
                "attempt_summary": "The actor looks around the current area.",
                "what_succeeds": ["The actor observes the immediate surroundings."],
                "what_fails": [],
                "blockers": [],
                "side_effects": [],
                "revealed_information": ["Existing scene context is available for narration."],
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
                    "effort_level": "low",
                    "interrupted": False,
                },
                "reasoning_short": "Looking around has no blocker.",
            }
        )
        adapter = _SequenceLLMAdapter([bad_response, repaired_response])
        service = ActionEvaluationService(llm_adapter=adapter)

        result = service.evaluate_action(
            raw_player_input="look around",
            route_decision=route_decision,
            entity_resolution=entity_resolution,
            session_state=session_state,
        )

        self.assertEqual(result["action_result"], "success")
        self.assertEqual(result["outcome_quality"], 55)
        self.assertEqual(len(adapter.calls), 2)

    def test_optional_unresolved_references_are_warnings_not_blockers(self) -> None:
        session_state = create_initial_session_state()
        adapter = _FakeLLMAdapter(
            {
                "action_result": "success",
                "outcome_quality": 50,
                "attempt_summary": "The actor proceeds with the declared action.",
                "what_succeeds": ["The main action can still proceed."],
                "what_fails": [],
                "blockers": [],
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
                    "effort_level": "low",
                    "interrupted": False,
                },
                "reasoning_short": "Optional unresolved references are not execution blockers.",
            }
        )
        service = ActionEvaluationService(llm_adapter=adapter)
        route_decision = {
            "action_category": "inspection",
            "expanded_player_intent": "look around",
            "primary_intent": "inspect surroundings",
            "secondary_elements": [],
            "possible_targets": [],
            "requested_agents": [],
            "narration_notes": [],
            "routing_reason": "Inspection intent is explicit.",
            "entity_resolution_hint": {"needed": False, "reason": "Broad inspection."},
        }
        entity_resolution: EntityResolutionResult = {
            "raw_input": "look around",
            "resolved_entities": [],
            "unresolved_mentions": [
                {
                    "source_text": "optional thing",
                    "span": None,
                    "expected_types": ["item"],
                    "truth_status": "unresolved",
                }
            ],
            "ambiguous_mentions": [],
            "annotations": [],
            "execution_status": "clear",
            "resolver_status": "has_unresolved",
            "debug": {
                "candidate_count": 0,
                "candidate_sources_used": [],
                "matches_considered": [],
                "semantic_resolver": {},
                "resolver_status": "has_unresolved",
            },
        }

        result = service.evaluate_action(
            raw_player_input="look around",
            route_decision=route_decision,
            entity_resolution=entity_resolution,
            session_state=session_state,
        )

        judge_input = json.loads(adapter.calls[0]["user_prompt"])
        self.assertEqual(judge_input["prechecked_facts"]["blocking_facts"], [])
        self.assertTrue(judge_input["prechecked_facts"]["warnings"])
        self.assertEqual(result["action_result"], "success")


if __name__ == "__main__":
    unittest.main()
