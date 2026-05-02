"""Router checks for the Entity Resolver hint boundary."""

from __future__ import annotations

import json
import unittest

from backend.modules.router.services.router_service import RouterService


class FakeLLM:
    """Small LLM adapter test double for RouterService."""

    def __init__(self, text: str) -> None:
        self.text = text

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        format_json: bool = False,
    ) -> dict[str, object]:
        return {
            "text": self.text,
            "provider": "test",
            "model": "fake",
            "used_mock": False,
        }


class RouterEntityHintTests(unittest.TestCase):
    """Verify Router hints resolution need without resolving entities."""

    def _router_input(self, raw_player_input: str) -> dict:
        return {
            "raw_player_input": raw_player_input,
            "game_mode": "exploration",
            "scene_context": {
                "game_mode": "exploration",
                "location": "market crossroads",
                "time_summary": "day 1 08:00",
            },
            "visible_entities_summary": [],
            "available_modules": ["npc_reaction"],
            "last_presented_choices": [],
            "active_features": [],
        }

    def test_router_can_request_entity_resolution_without_canonical_ids(self) -> None:
        llm_payload = {
            "action_category": "inspection",
            "expanded_player_intent": "use the compass",
            "primary_intent": "orient oneself",
            "attempted_method": "use a compass",
            "secondary_elements": [],
            "possible_targets": [],
            "requested_agents": [],
            "narration_notes": [],
            "routing_reason": "The player wants to use a concrete tool.",
            "entity_resolution_hint": {
                "needed": True,
                "reason": "The action depends on a referenced tool.",
            },
        }
        service = RouterService(llm_adapter=FakeLLM(json.dumps(llm_payload)))
        route = service.route_message(self._router_input("використати компас"))
        self.assertTrue(route["entity_resolution_hint"]["needed"])
        self.assertEqual(route["expanded_player_intent"], "use the compass")
        self.assertEqual(route["attempted_method"], "use a compass")
        self.assertNotIn("item_id", json.dumps(route))
        self.assertNotIn("old_compass", json.dumps(route))

    def test_router_fallback_does_not_hint_for_broad_look_around(self) -> None:
        service = RouterService(llm_adapter=FakeLLM(""))
        route = service.route_message(self._router_input("look around"))
        self.assertEqual(route["action_category"], "inspection")
        self.assertFalse(route["entity_resolution_hint"]["needed"])


if __name__ == "__main__":
    unittest.main()
