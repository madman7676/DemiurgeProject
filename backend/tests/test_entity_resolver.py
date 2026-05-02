"""Focused checks for LLM-assisted entity resolution and annotations."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from backend.core.game_state.services.session_service import create_initial_session_state
from backend.modules.entity_resolver.services.entity_resolver_service import (
    EntityResolverService,
)


class FakeSemanticMatcher:
    """Deterministic test double for the LLM resolver boundary."""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or {
            "resolved_entities": [],
            "unresolved_mentions": [],
            "ambiguous_mentions": [],
        }
        self.last_request: dict[str, Any] | None = None

    def resolve(self, request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        self.last_request = request
        return self.payload, {"invoked": True, "test_double": True}


class EntityResolverTests(unittest.TestCase):
    """Verify resolver behavior without heuristic word-list parsing."""

    def setUp(self) -> None:
        self.session_state = create_initial_session_state()
        self.session_state["npc_states"][0]["location"]["region_id"] = self.session_state["player_state"][
            "current_location"
        ]["region_id"]
        self.route = {
            "action_category": "inspection",
            "expanded_player_intent": "",
            "primary_intent": "",
            "secondary_elements": [],
            "possible_targets": [],
            "requested_agents": [],
            "narration_notes": [],
            "routing_reason": "",
            "entity_resolution_hint": {"needed": False, "reason": ""},
        }

    def test_inventory_item_resolves_to_canonical_id_with_deterministic_exact_match(self) -> None:
        service = EntityResolverService()
        self.route["expanded_player_intent"] = "take out the compass"
        result = service.resolve_entities("take out the compass", self.route, self.session_state)
        self.assertEqual(result["resolved_entities"][0]["entity_id"], "old_compass")
        self.assertEqual(result["annotations"][0]["display_text"].lower(), "compass")

    def test_skill_resolves_to_canonical_id_with_deterministic_exact_match(self) -> None:
        service = EntityResolverService()
        self.route["expanded_player_intent"] = "use awareness"
        result = service.resolve_entities("use awareness", self.route, self.session_state)
        self.assertEqual(result["resolved_entities"][0]["entity_type"], "skill")
        self.assertEqual(result["resolved_entities"][0]["entity_id"], "awareness")

    def test_currency_resolves_when_referenced(self) -> None:
        service = EntityResolverService()
        self.route["expanded_player_intent"] = "pay with coins"
        result = service.resolve_entities("pay with coins", self.route, self.session_state)
        self.assertEqual(result["resolved_entities"][0]["entity_type"], "currency")
        self.assertEqual(result["resolved_entities"][0]["entity_id"], "coin")

    def test_held_item_is_preferred_for_generic_reference(self) -> None:
        service = EntityResolverService()
        self.route["expanded_player_intent"] = "draw the compass"
        result = service.resolve_entities("draw the compass", self.route, self.session_state)
        self.assertEqual(result["resolved_entities"][0]["candidate_source"], "held")

    def test_visible_actor_resolves_if_available(self) -> None:
        service = EntityResolverService()
        self.route["action_category"] = "speech"
        self.route["expanded_player_intent"] = "say hello to Tomas Vey"
        result = service.resolve_entities("say hello to Tomas Vey", self.route, self.session_state)
        self.assertEqual(result["resolved_entities"][0]["entity_type"], "actor")
        self.assertEqual(result["resolved_entities"][0]["entity_id"], "npc_stationmaster_01")

    def test_scene_pool_entries_resolve_as_soft_scene(self) -> None:
        service = EntityResolverService()
        self.session_state["scene_entity_pool"] = [
            {
                "entity_type": "scene_entity",
                "entity_id": "scene:torch_on_wall",
                "name": "Torch on Wall",
                "aliases": ["torch", "wall torch"],
                "source": "narrator",
                "raw": {"kind": "fixture"},
            }
        ]
        self.route["expanded_player_intent"] = "inspect the torch"
        result = service.resolve_entities("inspect the torch", self.route, self.session_state)
        self.assertEqual(result["resolved_entities"][0]["truth_status"], "soft_scene")

    def test_explicit_contextual_candidates_resolve_as_plausible_only(self) -> None:
        service = EntityResolverService()
        self.session_state["contextual_candidates"] = [
            {
                "entity_type": "scene_entity",
                "entity_id": "road_stone",
                "name": "Road Stone",
                "aliases": ["stone"],
                "raw": {"source": "test_context"},
            }
        ]
        self.route["expanded_player_intent"] = "pick up the stone"
        result = service.resolve_entities("pick up the stone", self.route, self.session_state)
        self.assertTrue(result["resolved_entities"])
        self.assertEqual(result["resolved_entities"][0]["truth_status"], "plausible_contextual")

    def test_cross_language_reference_resolves_with_llm_without_alias(self) -> None:
        self.session_state["player_state"]["inventory"][0]["aliases"] = []
        self.session_state["player_state"]["held_items"][0]["aliases"] = []
        matcher = FakeSemanticMatcher(
            {
                "resolved_entities": [
                    {
                        "source_text": "компас",
                        "entity_type": "item",
                        "entity_id": "old_compass",
                        "canonical_name": "Old Compass",
                        "confidence": 0.94,
                        "reason": "semantic match",
                    }
                ],
                "unresolved_mentions": [],
                "ambiguous_mentions": [],
            }
        )
        service = EntityResolverService(semantic_matcher=matcher)
        self.route["expanded_player_intent"] = "use the compass"
        self.route["primary_intent"] = "orient oneself"
        self.route["entity_resolution_hint"] = {"needed": True, "reason": "Concrete tool reference."}
        result = service.resolve_entities("використати компас", self.route, self.session_state)
        self.assertEqual(result["resolved_entities"][0]["entity_id"], "old_compass")
        self.assertEqual(result["resolved_entities"][0]["match_method"], "semantic_llm")
        self.assertEqual(result["annotations"][0]["display_text"], "компас")
        self.assertEqual(matcher.last_request["router_output"]["expanded_player_intent"], "use the compass")

    def test_affordance_semantics_include_candidate_effect_data(self) -> None:
        matcher = FakeSemanticMatcher(
            {
                "resolved_entities": [
                    {
                        "source_text": "safe blink",
                        "entity_type": "skill",
                        "entity_id": "save_spot",
                        "canonical_name": "Save Spot",
                        "confidence": 0.91,
                        "reason": "The requested effect matches the skill description.",
                    }
                ],
                "unresolved_mentions": [],
                "ambiguous_mentions": [],
            }
        )
        service = EntityResolverService(semantic_matcher=matcher)
        self.route["expanded_player_intent"] = "blink to safety"
        self.route["primary_intent"] = "escape immediate danger"
        self.route["attempted_method"] = "use a quick safe teleport ability"
        self.route["entity_resolution_hint"] = {
            "needed": True,
            "reason": "The player appears to use or imply a specific capability.",
        }

        result = service.resolve_entities("safe blink звідси", self.route, self.session_state)

        self.assertEqual(result["resolved_entities"][0]["entity_id"], "save_spot")
        self.assertIn("description", result["resolved_entities"][0]["entity_data"])
        self.assertEqual(
            matcher.last_request["router_output"]["attempted_method"],
            "use a quick safe teleport ability",
        )
        save_spot_candidate = next(
            candidate
            for candidate in matcher.last_request["candidate_entities"]
            if candidate["entity_id"] == "save_spot"
        )
        self.assertIn("teleports", save_spot_candidate["description"])
        self.assertEqual(save_spot_candidate["effect"]["teleport_to"], "nearest_safe_spot")

    def test_low_confidence_semantic_resolution_becomes_unresolved(self) -> None:
        service = EntityResolverService(
            semantic_matcher=FakeSemanticMatcher(
                {
                    "resolved_entities": [
                        {
                            "source_text": "some trick",
                            "entity_type": "skill",
                            "entity_id": "save_spot",
                            "canonical_name": "Save Spot",
                            "confidence": 0.42,
                            "reason": "Weak guess.",
                        }
                    ],
                    "unresolved_mentions": [],
                    "ambiguous_mentions": [],
                }
            )
        )
        self.route["expanded_player_intent"] = "do some trick"
        self.route["attempted_method"] = "some unclear trick"
        self.route["entity_resolution_hint"] = {
            "needed": True,
            "reason": "The player may imply a capability.",
        }

        result = service.resolve_entities("роблю якийсь трюк", self.route, self.session_state)

        self.assertEqual(result["resolved_entities"], [])
        self.assertEqual(result["resolver_status"], "has_unresolved")
        self.assertEqual(result["unresolved_mentions"][0]["source_text"], "some trick")

    def test_cross_language_reference_without_candidate_becomes_unresolved(self) -> None:
        self.session_state["player_state"]["inventory"] = [
            {"item_id": "travel_cloak", "name": "Travel Cloak", "quantity": 1, "aliases": []}
        ]
        self.session_state["player_state"]["held_items"] = []
        service = EntityResolverService(
            semantic_matcher=FakeSemanticMatcher(
                {
                    "resolved_entities": [],
                    "unresolved_mentions": [
                        {"source_text": "компас", "type_hint": "item", "reason": "No matching candidate."}
                    ],
                    "ambiguous_mentions": [],
                }
            )
        )
        self.route["expanded_player_intent"] = "use the compass"
        self.route["entity_resolution_hint"] = {"needed": True, "reason": "Concrete tool reference."}
        result = service.resolve_entities("використати компас", self.route, self.session_state)
        self.assertEqual(result["execution_status"], "interrupted_before_execution")
        self.assertEqual(result["resolver_status"], "has_unresolved")
        self.assertEqual(result["unresolved_mentions"][0]["source_text"], "компас")

    def test_semantic_close_competitors_become_ambiguous(self) -> None:
        self.session_state["player_state"]["inventory"].append(
            {
                "item_id": "brass_compass",
                "name": "Brass Compass",
                "quantity": 1,
                "aliases": [],
            }
        )
        self.session_state["player_state"]["held_items"] = []
        self.session_state["player_state"]["inventory"][0]["aliases"] = []
        service = EntityResolverService(
            semantic_matcher=FakeSemanticMatcher(
                {
                    "resolved_entities": [],
                    "unresolved_mentions": [],
                    "ambiguous_mentions": [
                        {
                            "source_text": "компас",
                            "type_hint": "item",
                            "candidates": [
                                {"entity_id": "old_compass", "canonical_name": "Old Compass", "confidence": 0.82},
                                {"entity_id": "brass_compass", "canonical_name": "Brass Compass", "confidence": 0.76},
                            ],
                            "reason": "Both candidates are plausible.",
                        }
                    ],
                }
            )
        )
        self.route["expanded_player_intent"] = "use the compass"
        self.route["entity_resolution_hint"] = {"needed": True, "reason": "Concrete tool reference."}
        result = service.resolve_entities("використати компас", self.route, self.session_state)
        self.assertEqual(result["execution_status"], "interrupted_before_execution")
        self.assertEqual(result["resolver_status"], "has_ambiguous")
        self.assertTrue(result["ambiguous_mentions"])

    def test_invented_llm_ids_are_rejected(self) -> None:
        self.session_state["player_state"]["inventory"][0]["aliases"] = []
        self.session_state["player_state"]["held_items"][0]["aliases"] = []
        service = EntityResolverService(
            semantic_matcher=FakeSemanticMatcher(
                {
                    "resolved_entities": [
                        {
                            "source_text": "компас",
                            "entity_type": "item",
                            "entity_id": "invented_compass",
                            "canonical_name": "Invented Compass",
                            "confidence": 0.99,
                        }
                    ],
                    "unresolved_mentions": [],
                    "ambiguous_mentions": [],
                }
            )
        )
        self.route["expanded_player_intent"] = "use the compass"
        self.route["entity_resolution_hint"] = {"needed": True, "reason": "Concrete tool reference."}
        result = service.resolve_entities("використати компас", self.route, self.session_state)
        self.assertEqual(result["resolved_entities"], [])
        self.assertEqual(result["unresolved_mentions"][0]["source_text"], "компас")
        invalid_ids = result["debug"]["semantic_resolver"]["validation"]["invalid_or_invented_ids"]
        self.assertEqual(invalid_ids[0]["entity_id"], "invented_compass")

    def test_missing_exact_span_preserves_resolution_but_omits_annotation(self) -> None:
        service = EntityResolverService(
            semantic_matcher=FakeSemanticMatcher(
                {
                    "resolved_entities": [
                        {
                            "source_text": "compass",
                            "entity_type": "item",
                            "entity_id": "old_compass",
                            "canonical_name": "Old Compass",
                            "confidence": 0.9,
                        }
                    ],
                    "unresolved_mentions": [],
                    "ambiguous_mentions": [],
                }
            )
        )
        self.route["expanded_player_intent"] = "use the compass"
        self.route["entity_resolution_hint"] = {"needed": True, "reason": "Concrete tool reference."}
        result = service.resolve_entities("використати компас", self.route, self.session_state)
        self.assertEqual(result["resolved_entities"][0]["entity_id"], "old_compass")
        self.assertIsNone(result["resolved_entities"][0]["span"])
        self.assertEqual(result["annotations"], [])

    def test_empty_llm_result_with_hint_creates_unresolved_from_router_intent(self) -> None:
        self.session_state["player_state"]["inventory"][0]["aliases"] = []
        self.session_state["player_state"]["held_items"][0]["aliases"] = []
        service = EntityResolverService(semantic_matcher=FakeSemanticMatcher())
        self.route["expanded_player_intent"] = "use the compass"
        self.route["entity_resolution_hint"] = {"needed": True, "reason": "Concrete tool reference."}
        result = service.resolve_entities("використати компас", self.route, self.session_state)
        self.assertEqual(result["resolver_status"], "has_unresolved")
        self.assertEqual(result["unresolved_mentions"][0]["source_text"], "use the compass")

    def test_provider_debug_lists_inventory_and_held_before_dedupe(self) -> None:
        service = EntityResolverService()
        self.route["expanded_player_intent"] = "draw the compass"
        result = service.resolve_entities("draw the compass", self.route, self.session_state)
        self.assertIn("inventory", result["debug"]["candidate_sources_used"])
        self.assertIn("held", result["debug"]["candidate_sources_used"])

    def test_actions_without_entity_mentions_stay_clear(self) -> None:
        service = EntityResolverService()
        self.route["expanded_player_intent"] = "look around"
        self.route["entity_resolution_hint"] = {"needed": False, "reason": "Broad inspection."}
        result = service.resolve_entities("look around", self.route, self.session_state)
        self.assertEqual(result["execution_status"], "clear")
        self.assertEqual(result["resolved_entities"], [])

    def test_no_compass_specific_hardcoding_exists_in_resolver(self) -> None:
        service_source = Path("backend/modules/entity_resolver/services/entity_resolver_service.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("old_compass", service_source)
        self.assertNotIn("компас", service_source)
        self.assertNotIn("CONTEXTUAL_LOCATION_MAP", service_source)
        self.assertNotIn("OBJECT_TRIGGER_WORDS", service_source)


if __name__ == "__main__":
    unittest.main()
