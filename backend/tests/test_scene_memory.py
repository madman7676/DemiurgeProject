"""Scene memory checks for narrator marker persistence."""

from __future__ import annotations

import unittest

from backend.core.game_state.services.scene_memory_service import apply_narrator_scene_memory
from backend.core.game_state.services.session_service import create_initial_session_state
from backend.modules.entity_resolver.services.entity_resolver_service import EntityResolverService
from backend.modules.narrator.services.narrator_service import extract_narrator_mentions


def _clear_resolution() -> dict:
    return {
        "raw_input": "",
        "resolved_entities": [],
        "unresolved_mentions": [],
        "ambiguous_mentions": [],
        "annotations": [],
        "execution_status": "clear",
        "resolver_status": "clear",
        "debug": {},
    }


class SceneMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session_state = create_initial_session_state()
        self.resolution = _clear_resolution()

    def test_extracts_structured_narrator_mentions(self) -> None:
        mentions = extract_narrator_mentions(
            "Ти бачиш [[scene_entity:available|кіоск]], згадуєш [[reference:known_reference|храм]], "
            "і тримаєш [[player_entity|компас]]."
        )

        self.assertEqual(mentions["scene_entity_mentions"][0]["status"], "available")
        self.assertEqual(mentions["reference_mentions"][0]["status"], "known_reference")
        self.assertEqual(mentions["player_entity_mentions"][0]["type"], "player_entity")

    def test_available_scene_entity_enters_scene_pool_and_resolves_next_turn(self) -> None:
        text = "Попереду [[scene_entity:available|кам'яний колодязь]]."
        mentions = extract_narrator_mentions(text)

        apply_narrator_scene_memory(self.session_state, text, mentions, self.resolution, current_turn=1)

        self.assertEqual(len(self.session_state["scene_entity_pool"]), 1)
        self.assertEqual(self.session_state["scene_entity_pool"][0]["status"], "available")
        service = EntityResolverService()
        route = {
            "action_category": "inspection",
            "expanded_player_intent": "inspect the кам'яний колодязь",
            "primary_intent": "inspect scene object",
            "secondary_elements": [],
            "possible_targets": [],
            "requested_agents": [],
            "narration_notes": [],
            "routing_reason": "",
            "entity_resolution_hint": {"needed": False, "reason": ""},
        }
        result = service.resolve_entities("оглянути кам'яний колодязь", route, self.session_state)
        self.assertEqual(result["resolved_entities"][0]["truth_status"], "soft_scene")

    def test_repeated_mentions_update_without_duplicates_and_available_wins(self) -> None:
        first = "Десь позаду [[scene_entity:background|старий фонтан]]."
        apply_narrator_scene_memory(
            self.session_state,
            first,
            extract_narrator_mentions(first),
            self.resolution,
            current_turn=1,
        )
        second = "Тепер поруч [[scene_entity:available|старий фонтан]]."
        apply_narrator_scene_memory(
            self.session_state,
            second,
            extract_narrator_mentions(second),
            self.resolution,
            current_turn=2,
        )

        self.assertEqual(len(self.session_state["scene_entity_pool"]), 1)
        entry = self.session_state["scene_entity_pool"][0]
        self.assertEqual(entry["status"], "available")
        self.assertEqual(entry["mention_count"], 2)
        self.assertEqual(entry["last_seen_turn"], 2)

    def test_reference_and_player_entity_do_not_enter_scene_pool(self) -> None:
        text = "[[reference:known_reference|старий храм]] і [[player_entity|Old Compass]]."
        debug = apply_narrator_scene_memory(
            self.session_state,
            text,
            extract_narrator_mentions(text),
            self.resolution,
            current_turn=1,
        )

        self.assertEqual(self.session_state["scene_entity_pool"], [])
        self.assertEqual(self.session_state["reference_pool"][0]["name"], "старий храм")
        self.assertIn("Validated player_entity", debug["validation_warnings"][0])

    def test_invalid_player_entity_does_not_create_memory(self) -> None:
        text = "[[player_entity|зоряний меч]]."
        debug = apply_narrator_scene_memory(
            self.session_state,
            text,
            extract_narrator_mentions(text),
            self.resolution,
            current_turn=1,
        )

        self.assertEqual(self.session_state["scene_entity_pool"], [])
        self.assertEqual(self.session_state["reference_pool"], [])
        self.assertIn("Ignored invalid player_entity", debug["validation_warnings"][0])

    def test_unresolved_turn_reference_is_not_stored_as_available(self) -> None:
        resolution = _clear_resolution()
        resolution["unresolved_mentions"] = [
            {
                "source_text": "ключ",
                "span": None,
                "expected_types": ["item"],
                "truth_status": "unresolved",
            }
        ]
        text = "Ти бачиш [[scene_entity:available|ключ]]."

        apply_narrator_scene_memory(
            self.session_state,
            text,
            extract_narrator_mentions(text),
            resolution,
            current_turn=1,
        )

        self.assertEqual(self.session_state["scene_entity_pool"], [])

    def test_location_change_clears_scene_pool_but_keeps_references(self) -> None:
        text = "[[scene_entity:available|кіоск]] біля [[reference:known_reference|храму]]."
        apply_narrator_scene_memory(
            self.session_state,
            text,
            extract_narrator_mentions(text),
            self.resolution,
            current_turn=1,
        )
        self.session_state["player_state"]["current_location"] = {"region_id": "new_place"}

        apply_narrator_scene_memory(
            self.session_state,
            "",
            extract_narrator_mentions(""),
            self.resolution,
            current_turn=2,
        )

        self.assertEqual(self.session_state["scene_entity_pool"], [])
        self.assertEqual(len(self.session_state["reference_pool"]), 1)

    def test_stale_scene_entities_are_removed(self) -> None:
        text = "[[scene_entity:available|кіоск]]."
        apply_narrator_scene_memory(
            self.session_state,
            text,
            extract_narrator_mentions(text),
            self.resolution,
            current_turn=1,
            stale_turn_threshold=2,
        )

        apply_narrator_scene_memory(
            self.session_state,
            "",
            extract_narrator_mentions(""),
            self.resolution,
            current_turn=4,
            stale_turn_threshold=2,
        )

        self.assertEqual(self.session_state["scene_entity_pool"], [])


if __name__ == "__main__":
    unittest.main()
