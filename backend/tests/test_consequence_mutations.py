"""Phase 2 non-transfer mutation checks for the Consequences layer."""

from __future__ import annotations

import unittest

from backend.core.game_state.services.consequence_service import apply_consequence_layer
from backend.core.game_state.services.session_service import create_initial_session_state


def _action_result(state_intents: dict) -> dict:
    default_state_intents = {
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
    }
    default_state_intents.update(state_intents)
    return {
        "action_type": "inspection",
        "raw_player_input": "test action",
        "expanded_player_intent": "test action",
        "interpreted_intent": {
            "primary_goal": "test action",
            "target_ids": [],
            "approach": "inspection",
            "notes": [],
        },
        "action_result": "success",
        "outcome_quality": 55,
        "attempt_summary": "The action is resolved.",
        "what_succeeds": [],
        "what_fails": [],
        "blockers": [],
        "side_effects": [],
        "proposed_side_effects": [],
        "applied_side_effects": [],
        "quality_side_effect_chance": 0.0,
        "quality_side_effect_applied": False,
        "revealed_information": [],
        "risk_flags": [],
        "state_intents": default_state_intents,
        "time_hints": {"duration_class": "short", "effort_level": "low", "interrupted": False},
        "reasoning_short": "Test.",
        "outcome_summary": "",
        "applied_changes": [],
        "change_summary": [],
        "consequence_debug": {},
        "state_changes": [],
        "npc_reactions": [],
        "time_cost": {"amount": 1, "unit": "minute"},
        "narration_notes": [],
        "discovered_rule_candidate": None,
    }


class ConsequenceMutationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session_state = create_initial_session_state()

    def test_add_new_skill_updates_player_skills(self) -> None:
        result = apply_consequence_layer(
            self.session_state,
            _action_result(
                {
                    "skill_changes": [
                        {
                            "op": "add",
                            "skill_id": "fireball",
                            "skill_data": {"skill_id": "fireball", "name": "Fireball", "level": 1},
                            "amount": 1,
                        }
                    ]
                }
            ),
            "inspection",
        )

        self.assertTrue(any(skill["skill_id"] == "fireball" for skill in self.session_state["player_state"]["skills"]))
        self.assertEqual(result["change_summary"][0]["text"], "Skill learned: Fireball")

    def test_level_existing_skill_updates_level(self) -> None:
        result = apply_consequence_layer(
            self.session_state,
            _action_result(
                {
                    "skill_changes": [
                        {"op": "level_up", "skill_id": "awareness", "amount": 1}
                    ]
                }
            ),
            "inspection",
        )

        awareness = next(skill for skill in self.session_state["player_state"]["skills"] if skill["skill_id"] == "awareness")
        self.assertEqual(awareness["level"], 3)
        self.assertEqual(result["change_summary"][0]["text"], "Skill improved: Awareness 2 -> 3")

    def test_increase_and_decrease_stat_updates_value(self) -> None:
        result = apply_consequence_layer(
            self.session_state,
            _action_result(
                {
                    "stat_changes": [
                        {"op": "increase", "stat_id": "resolve", "amount": 1}
                    ]
                }
            ),
            "inspection",
        )

        resolve = next(stat for stat in self.session_state["player_state"]["stats"] if stat["stat_id"] == "resolve")
        self.assertEqual(resolve["value"], 5)
        self.assertEqual(result["change_summary"][0]["text"], "Stat increased: Resolve +1")

    def test_spending_currency_reduces_amount_and_blocks_if_insufficient(self) -> None:
        result = apply_consequence_layer(
            self.session_state,
            _action_result(
                {
                    "currency_changes": [
                        {"op": "spend", "currency_id": "coin", "amount": 3},
                        {"op": "spend", "currency_id": "coin", "amount": 99},
                    ]
                }
            ),
            "inspection",
        )

        coin = next(currency for currency in self.session_state["player_state"]["currencies"] if currency["currency_id"] == "coin")
        self.assertEqual(coin["amount"], 4)
        self.assertEqual(result["change_summary"], [{"kind": "negative", "text": "Spent: 3 Coin"}])
        self.assertEqual(len(result["consequence_debug"]["state_mutations"]["skipped_changes"]), 1)

    def test_add_status_effect_creates_or_refreshes_without_duplicates(self) -> None:
        first = apply_consequence_layer(
            self.session_state,
            _action_result(
                {
                    "status_effect_changes": [
                        {
                            "op": "add",
                            "effect_id": "poisoned",
                            "effect_data": {"effect_id": "poisoned", "name": "Poisoned"},
                            "duration": 3,
                        }
                    ]
                }
            ),
            "inspection",
        )
        second = apply_consequence_layer(
            self.session_state,
            _action_result(
                {
                    "status_effect_changes": [
                        {
                            "op": "refresh",
                            "effect_id": "poisoned",
                            "effect_data": {"effect_id": "poisoned", "name": "Poisoned"},
                            "duration": 5,
                        }
                    ]
                }
            ),
            "inspection",
        )

        effects = [effect for effect in self.session_state["player_state"]["status_effects"] if effect["effect_id"] == "poisoned"]
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["remaining_duration"], 5)
        self.assertEqual(first["change_summary"][0]["text"], "Gained: Poisoned")
        self.assertEqual(second["change_summary"][0]["text"], "Refreshed: Poisoned")

    def test_remove_status_effect(self) -> None:
        self.session_state["player_state"]["status_effects"] = [
            {"effect_id": "bleeding", "name": "Bleeding", "remaining_duration": 2}
        ]

        result = apply_consequence_layer(
            self.session_state,
            _action_result(
                {
                    "status_effect_changes": [
                        {"op": "remove", "effect_id": "bleeding"}
                    ]
                }
            ),
            "inspection",
        )

        self.assertEqual(self.session_state["player_state"]["status_effects"], [])
        self.assertEqual(result["change_summary"][0]["text"], "Removed: Bleeding")


if __name__ == "__main__":
    unittest.main()
