"""Focused checks for the tag-driven Lite state system."""

import unittest

from backend.api.routes import RouteContext, apply_player_changes, process_lite_turn
from backend.core.state import create_initial_game_state
from backend.core.tag_parser import parse_tags, strip_player_change_tags, strip_tags


class LitePipelineTest(unittest.TestCase):
    def test_parse_entities_player_changes_and_malformed_tags(self):
        parsed = parse_tags(
            "You find [[entity:item|rusty_knife_01|rusty knife|available|K]] "
            "[[player_change|add_item:rusty_knife_01]] "
            "[[entity:unknown|bad|bad|available]] "
            "[[player_change|upgrade_skill:awareness]]."
        )

        self.assertEqual(parsed["entities"][0]["id"], "rusty_knife_01")
        self.assertEqual(parsed["entities"][0]["icon"], "K")
        self.assertEqual(parsed["player_changes"][0]["command"], "add_item")
        self.assertEqual(
            [tag["reason"] for tag in parsed["malformed_or_skipped_tags"]],
            ["unknown_entity_class", "unknown_player_change"],
        )

    def test_apply_state_changes_and_location(self):
        state = create_initial_game_state()
        parsed = parse_tags(
            "[[entity:item|rusty_knife_01|rusty knife|available|K]]"
            "[[entity:currency|gold|золото|available|G]]"
            "[[entity:skill|fire_bolt|вогняний заряд|available|F]]"
            "[[entity:place|market_lane|ринковий провулок|available|P]]"
            "[[player_change|add_item:rusty_knife_01]]"
            "[[player_change|add_currency:gold:10]]"
            "[[player_change|add_skill:fire_bolt]]"
            "[[player_change|set_location:market_lane]]"
        )
        entities = [
            {
                "id": entity["id"],
                "class": entity["class"],
                "name": entity["name"],
                "visibility": entity["visibility"],
                "icon": entity["icon"],
                "last_seen_turn": 1,
            }
            for entity in parsed["entities"]
        ]

        applied, skipped = apply_player_changes(state, parsed["player_changes"], entities)

        self.assertEqual(skipped, [])
        self.assertTrue(any(item["id"] == "rusty_knife_01" for item in state["player"]["inventory"]))
        self.assertEqual(next(currency for currency in state["player"]["currencies"] if currency["id"] == "gold")["amount"], 10)
        self.assertTrue(any(skill["id"] == "fire_bolt" for skill in state["player"]["skills"]))
        self.assertEqual(state["scene"]["location"]["id"], "market_lane")
        self.assertEqual([change["action"] for change in applied], ["add_item", "add_currency", "add_skill", "set_location"])

    def test_unknown_currency_add_is_skipped(self):
        state = create_initial_game_state()
        parsed = parse_tags("[[player_change|add_currency:gems:4]]")

        applied, skipped = apply_player_changes(state, parsed["player_changes"], [])

        self.assertEqual(applied, [])
        self.assertEqual(skipped[0]["reason"], "invalid_reference")
        self.assertFalse(any(currency["id"] == "gems" for currency in state["player"]["currencies"]))

    def test_strip_tags_keeps_clean_narration(self):
        self.assertEqual(
            strip_tags("Текст [[entity:item|x|річ|available|I]]\n[[player_change|add_item:x]]"),
            "Текст",
        )

    def test_ui_response_preserves_entity_tags_and_hides_player_changes(self):
        class FakeNarrator:
            def narrate(self, player_input, session_state, on_token=None):
                return (
                    "Ти бачиш [[entity:npc|merchant_01|торговець|available|M]] біля прилавка. "
                    "[[entity:item|rusty_knife_01|іржавий ніж|available|K]] лежить поруч.\n"
                    "[[player_change|add_item:rusty_knife_01]]"
                )

        class FakeStore:
            def __init__(self):
                self.state = create_initial_game_state()

            def get_session(self):
                return self.state

        result = process_lite_turn("оглянутись", RouteContext(FakeStore(), FakeNarrator()))
        assistant = result["recent_messages"][-1]

        self.assertIn("[[entity:npc|merchant_01|торговець|available|M]]", assistant["text"])
        self.assertNotIn("[[player_change|add_item:rusty_knife_01]]", assistant["text"])
        self.assertEqual(assistant["change_summary"], [{"kind": "add_item", "text": "Отримано: іржавий ніж"}])
        self.assertEqual(result["history"][-1]["narrator_response_clean"], "Ти бачиш біля прилавка. лежить поруч.")

    def test_scene_entities_persist_and_merge_without_location_change(self):
        class FakeNarrator:
            responses = [
                "Тут є [[entity:npc|merchant_01|торговець|available|M]].",
                "Торговець киває. [[entity:item|apple_01|яблуко|available|A]] лежить поруч.",
            ]

            def narrate(self, player_input, session_state, on_token=None):
                return self.responses.pop(0)

        class FakeStore:
            def __init__(self):
                self.state = create_initial_game_state()

            def get_session(self):
                return self.state

        store = FakeStore()
        narrator = FakeNarrator()
        process_lite_turn("оглянутись", RouteContext(store, narrator))
        result = process_lite_turn("поговорити", RouteContext(store, narrator))
        entity_ids = [entity["id"] for entity in result["visible_state"]["scene"]["entities"]]

        self.assertEqual(entity_ids, ["merchant_01", "apple_01"])
        self.assertFalse(result["debug"]["location_changed"])
        self.assertEqual(result["debug"]["scene_entities_added"][0]["id"], "apple_01")

    def test_location_change_clears_previous_scene_entities(self):
        class FakeNarrator:
            responses = [
                "Тут є [[entity:npc|merchant_01|торговець|available|M]].",
                "Ти переходиш до [[entity:place|market_lane|ринковий провулок|available|P]], де стоїть [[entity:npc|guard_01|вартовий|available|G]]. [[player_change|set_location:market_lane]]",
            ]

            def narrate(self, player_input, session_state, on_token=None):
                return self.responses.pop(0)

        class FakeStore:
            def __init__(self):
                self.state = create_initial_game_state()

            def get_session(self):
                return self.state

        store = FakeStore()
        narrator = FakeNarrator()
        process_lite_turn("оглянутись", RouteContext(store, narrator))
        result = process_lite_turn("йду далі", RouteContext(store, narrator))
        entity_ids = [entity["id"] for entity in result["visible_state"]["scene"]["entities"]]

        self.assertNotIn("merchant_01", entity_ids)
        self.assertIn("guard_01", entity_ids)
        self.assertTrue(result["debug"]["location_changed"])
        self.assertEqual(result["debug"]["scene_entities_cleared_due_to_location_change"][0]["id"], "merchant_01")

    def test_added_item_is_removed_from_scene_entities(self):
        class FakeNarrator:
            def narrate(self, player_input, session_state, on_token=None):
                return (
                    "Ти береш [[entity:item|rusty_knife_01|іржавий ніж|available|K]]. "
                    "[[player_change|add_item:rusty_knife_01]]"
                )

        class FakeStore:
            def __init__(self):
                self.state = create_initial_game_state()

            def get_session(self):
                return self.state

        result = process_lite_turn("беру ніж", RouteContext(FakeStore(), FakeNarrator()))

        self.assertFalse(any(entity["id"] == "rusty_knife_01" for entity in result["visible_state"]["scene"]["entities"]))
        self.assertEqual(result["debug"]["scene_entities_removed_due_to_player_change"][0]["id"], "rusty_knife_01")

    def test_strip_player_change_tags_keeps_entity_tags(self):
        text = (
            "Ти бачиш [[entity:npc|merchant_01|торговець|available|M]]. "
            "[[player_change|add_item:knife]]"
        )
        self.assertEqual(
            strip_player_change_tags(text),
            "Ти бачиш [[entity:npc|merchant_01|торговець|available|M]].",
        )


if __name__ == "__main__":
    unittest.main()
