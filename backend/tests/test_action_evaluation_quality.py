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


class _FakeLLMAdapter:
    """Small stub that returns deterministic Judge JSON."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def generate_text(self, system_prompt: str, user_prompt: str) -> dict[str, object]:
        return {
            "text": json.dumps(self._payload),
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

        service = ActionEvaluationService(
            llm_adapter=_FakeLLMAdapter(
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
        )

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

        result = service.evaluate_action(
            raw_player_input="look around",
            route_decision=route_decision,
            session_state=session_state,
        )

        self.assertEqual(result["expanded_player_intent"], "look around the area")
        self.assertEqual(result["outcome_quality"], 50)
        self.assertEqual(result["proposed_side_effects"], [])
        self.assertEqual(result["applied_side_effects"], [])


if __name__ == "__main__":
    unittest.main()
