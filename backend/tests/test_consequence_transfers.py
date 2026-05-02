"""Phase 1 state-transfer checks for the Consequences layer."""

from __future__ import annotations

import unittest

from backend.core.game_state.services.consequence_service import apply_consequence_layer
from backend.core.game_state.services.session_service import create_initial_session_state
from backend.modules.entity_resolver.services.entity_resolver_service import EntityResolverService


def _action_result(transfers: list[dict]) -> dict:
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
        "state_intents": {
            "position_change": None,
            "entity_transfers": transfers,
            "resource_changes": {},
            "status_changes": [],
            "relationship_signals": [],
            "environment_changes": [],
        },
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


class ConsequenceTransferTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session_state = create_initial_session_state()
        self.session_state["player_state"]["inventory"] = []
        self.session_state["player_state"]["equipped_items"] = []
        self.session_state["player_state"]["held_items"] = []
        self.session_state["scene_pool"] = []
        self.session_state["scene_entity_pool"] = self.session_state["scene_pool"]

    def _add_scene_entity(self, entity_id: str = "scene:stone", entity_type: str = "scene_entity") -> None:
        self.session_state["scene_pool"].append(
            {
                "entity_id": entity_id,
                "name": "Stone",
                "normalized_name": "stone",
                "entity_type": entity_type,
                "status": "available",
                "truth_status": "soft_scene",
                "scene_id": "stonemarket",
                "location_id": "stonemarket",
                "aliases": ["Stone"],
                "source": "scene_pool",
                "first_seen_turn": 0,
                "last_seen_turn": 0,
                "mention_count": 1,
                "raw": {"source": "test"},
            }
        )

    def test_taking_scene_item_moves_it_to_inventory(self) -> None:
        self._add_scene_entity()

        result = apply_consequence_layer(
            self.session_state,
            _action_result(
                [
                    {
                        "entity_id": "scene:stone",
                        "entity_type": "scene_entity",
                        "from": "scene_pool",
                        "to": "inventory",
                        "quantity": 1,
                    }
                ]
            ),
            "inspection",
        )

        self.assertEqual(self.session_state["scene_pool"], [])
        self.assertEqual(self.session_state["player_state"]["inventory"][0]["item_id"], "scene:stone")
        self.assertEqual(result["applied_changes"][0]["summary_label"], "Picked up")
        self.assertEqual(result["change_summary"][0]["text"], "Picked up: Stone")

    def test_dropping_inventory_item_moves_it_to_scene_pool(self) -> None:
        self.session_state["player_state"]["inventory"] = [
            {"item_id": "stone", "name": "Stone", "quantity": 1}
        ]

        result = apply_consequence_layer(
            self.session_state,
            _action_result(
                [
                    {
                        "entity_id": "stone",
                        "entity_type": "item",
                        "from": "inventory",
                        "to": "scene_pool",
                        "quantity": 1,
                    }
                ]
            ),
            "inspection",
        )

        self.assertEqual(self.session_state["player_state"]["inventory"], [])
        self.assertEqual(self.session_state["scene_pool"][0]["entity_id"], "stone")
        self.assertEqual(result["change_summary"][0]["text"], "Dropped: Stone")

    def test_equipping_inventory_item_moves_it_to_equipped(self) -> None:
        self.session_state["player_state"]["inventory"] = [
            {"item_id": "stone", "name": "Stone", "quantity": 1}
        ]

        apply_consequence_layer(
            self.session_state,
            _action_result(
                [
                    {
                        "entity_id": "stone",
                        "entity_type": "item",
                        "from": "inventory",
                        "to": "equipped",
                        "quantity": 1,
                    }
                ]
            ),
            "inspection",
        )

        self.assertEqual(self.session_state["player_state"]["inventory"], [])
        self.assertEqual(self.session_state["player_state"]["equipped_items"][0]["item_id"], "stone")
        self.assertEqual(self.session_state["player_state"]["held_items"][0]["item_id"], "stone")

    def test_unequipping_returns_item_to_inventory(self) -> None:
        self.session_state["player_state"]["equipped_items"] = [
            {"item_id": "stone", "name": "Stone", "quantity": 1}
        ]
        self.session_state["player_state"]["held_items"] = [
            {"item_id": "stone", "name": "Stone", "quantity": 1}
        ]

        apply_consequence_layer(
            self.session_state,
            _action_result(
                [
                    {
                        "entity_id": "stone",
                        "entity_type": "item",
                        "from": "equipped",
                        "to": "inventory",
                        "quantity": 1,
                    }
                ]
            ),
            "inspection",
        )

        self.assertEqual(self.session_state["player_state"]["equipped_items"], [])
        self.assertEqual(self.session_state["player_state"]["inventory"][0]["item_id"], "stone")

    def test_actor_scene_entity_cannot_move_to_inventory(self) -> None:
        self._add_scene_entity(entity_id="npc:guard", entity_type="actor")

        result = apply_consequence_layer(
            self.session_state,
            _action_result(
                [
                    {
                        "entity_id": "npc:guard",
                        "entity_type": "actor",
                        "from": "scene_pool",
                        "to": "inventory",
                        "quantity": 1,
                    }
                ]
            ),
            "inspection",
        )

        self.assertEqual(len(self.session_state["scene_pool"]), 1)
        self.assertEqual(result["applied_changes"], [])
        self.assertIn("Actors/NPCs", result["consequence_debug"]["entity_transfers"]["skipped_changes"][0]["reason"])

    def test_resolver_uses_moved_entity_from_new_container(self) -> None:
        self._add_scene_entity()
        apply_consequence_layer(
            self.session_state,
            _action_result(
                [
                    {
                        "entity_id": "scene:stone",
                        "entity_type": "scene_entity",
                        "from": "scene_pool",
                        "to": "inventory",
                        "quantity": 1,
                    }
                ]
            ),
            "inspection",
        )
        route = {
            "action_category": "inspection",
            "expanded_player_intent": "use Stone",
            "primary_intent": "use Stone",
            "attempted_method": "use Stone",
            "secondary_elements": [],
            "possible_targets": [],
            "requested_agents": [],
            "narration_notes": [],
            "routing_reason": "",
            "entity_resolution_hint": {"needed": False, "reason": ""},
        }

        result = EntityResolverService().resolve_entities("use Stone", route, self.session_state)

        self.assertEqual(result["resolved_entities"][0]["candidate_source"], "inventory")


if __name__ == "__main__":
    unittest.main()
