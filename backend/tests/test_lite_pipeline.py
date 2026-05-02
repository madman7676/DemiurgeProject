"""Focused checks for the Lite tag parser and state application."""

import unittest

from backend.api.routes import apply_player_changes
from backend.core.scene_memory import apply_scene_memory
from backend.core.state import create_initial_session_state
from backend.core.tag_parser import parse_tags


class LitePipelineTest(unittest.TestCase):
    def test_parse_entity_and_player_change_tags(self):
        parsed = parse_tags(
            "You find [[entity:item|rusty_knife_01|rusty knife|available]] "
            "[[player_change|add_item:rusty_knife_01]] [[player_change|add_gold:10]]."
        )

        self.assertEqual(parsed["entities"][0]["entity_id"], "rusty_knife_01")
        self.assertEqual(parsed["entities"][0]["name"], "rusty knife")
        self.assertEqual(
            [tag["change"] for tag in parsed["player_changes"]],
            ["add_item:rusty_knife_01", "add_gold:10"],
        )

    def test_apply_scene_memory_and_player_changes(self):
        session = create_initial_session_state()
        parsed = parse_tags(
            "[[entity:item|rusty_knife_01|rusty knife|available]]"
            "[[player_change|add_item:rusty_knife_01]]"
            "[[player_change|add_gold:10]]"
        )

        scene_changes = apply_scene_memory(session, parsed["entities"])
        player_changes = apply_player_changes(session, parsed["player_changes"])

        self.assertEqual(scene_changes[0]["action"], "created")
        self.assertTrue(
            any(item["item_id"] == "rusty_knife_01" for item in session["player_state"]["inventory"])
        )
        coin = next(
            currency for currency in session["player_state"]["currencies"] if currency["currency_id"] == "coin"
        )
        self.assertEqual(coin["amount"], 17)
        self.assertEqual([change["action"] for change in player_changes], ["add_item", "add_gold"])


if __name__ == "__main__":
    unittest.main()
