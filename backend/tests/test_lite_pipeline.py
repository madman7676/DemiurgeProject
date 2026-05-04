"""Focused checks for the tag-driven Lite state system."""

import unittest

from backend.api.routes import apply_player_changes
from backend.core.state import create_initial_game_state
from backend.core.tag_parser import parse_tags, strip_tags


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


if __name__ == "__main__":
    unittest.main()
