"""Focused checks for the tag-driven Lite state system."""

import unittest

from backend.api.routes import RouteContext, apply_player_changes, process_lite_turn
from backend.config import Settings
from backend.core.state import create_initial_game_state
from backend.core.tag_parser import parse_tags, strip_player_change_tags, strip_tags
from backend.llm.client import OllamaLLMClient
from backend.llm.narrator import Narrator


class LitePipelineTest(unittest.TestCase):
    def test_ollama_payload_includes_generation_options(self):
        settings = Settings(
            model="test-model",
            llm_url="http://localhost:11434/api/generate",
            host="127.0.0.1",
            port=8000,
            llm_timeout_seconds=240,
            ollama_num_predict=1024,
            ollama_num_ctx=8192,
            ollama_temperature=0.7,
            allow_mock_fallback=True,
        )
        client = OllamaLLMClient(settings)

        payload = client._build_payload("system", "prompt", stream=True)

        self.assertEqual(payload["model"], "test-model")
        self.assertTrue(payload["stream"])
        self.assertEqual(
            payload["options"],
            {"num_predict": 1024, "num_ctx": 8192, "temperature": 0.7},
        )

    def test_narrator_diagnostics_detect_unclosed_known_tag(self):
        class FakeLLMAdapter:
            last_diagnostics = {
                "model": "test-model",
                "options": {"num_predict": 1024, "num_ctx": 8192, "temperature": 0.7},
                "done": True,
                "done_reason": "length",
                "stream_error": None,
            }

            def generate_text(self, system_prompt, user_prompt):
                return {"text": ""}

            def stream_text(self, system_prompt, user_prompt):
                yield "Текст [[entity:item|potion_01|зілля|available|"

        narrator = Narrator(FakeLLMAdapter())

        text = narrator.narrate("оглянутись", create_initial_game_state(), on_token=lambda chunk: None)

        self.assertEqual(text, "Текст [[entity:item|potion_01|зілля|available|")
        self.assertEqual(narrator.last_diagnostics["done_reason"], "length")
        self.assertEqual(narrator.last_diagnostics["raw_response_length"], len(text))
        self.assertTrue(narrator.last_diagnostics["has_unclosed_tag"])
        self.assertTrue(narrator.last_diagnostics["ends_inside_known_tag"])
        self.assertEqual(narrator.last_diagnostics["ends_inside_tag_kind"], "entity")

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
        self.assertEqual(parsed["scene_changes"], [])
        self.assertEqual(
            [tag["reason"] for tag in parsed["malformed_or_skipped_tags"]],
            ["unknown_entity_class", "unknown_player_change"],
        )

    def test_parse_scene_changes_separately(self):
        parsed = parse_tags(
            "[[entity:item|ceramic_shards_01|керамічні уламки|available|C]]"
            "[[scene_change|remove_entity:ceramic_01]]"
        )

        self.assertEqual(parsed["entities"][0]["id"], "ceramic_shards_01")
        self.assertEqual(parsed["player_changes"], [])
        self.assertEqual(parsed["scene_changes"][0]["command"], "remove_entity")
        self.assertEqual(parsed["scene_changes"][0]["args"], ["ceramic_01"])

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
            strip_tags(
                "Текст [[entity:item|x|річ|available|I]]\n"
                "[[player_change|add_item:x]][[scene_change|remove_entity:y]]"
            ),
            "Текст",
        )

    def test_ui_response_preserves_entity_tags_and_hides_player_changes(self):
        class FakeNarrator:
            last_diagnostics = {
                "model": "fake-model",
                "options": {"num_predict": 1024, "num_ctx": 8192, "temperature": 0.7},
                "done_reason": "stop",
                "raw_response_length": 0,
                "has_unclosed_tag": False,
                "stream_error": None,
            }

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
        self.assertEqual(result["debug"]["llm_diagnostics"]["model"], "fake-model")
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
        self.assertFalse(any(entity["id"] == "market_lane" for entity in result["visible_state"]["scene"]["entities"]))
        self.assertEqual(
            result["debug"]["scene_entities_skipped_due_to_ownership"][0]["reason"],
            "target_location",
        )

    def test_added_item_is_skipped_before_scene_storage(self):
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
        self.assertEqual(result["debug"]["scene_entities_removed_due_to_player_change"], [])
        self.assertEqual(
            result["debug"]["scene_entities_skipped_due_to_ownership"],
            [
                {
                    "id": "rusty_knife_01",
                    "class": "item",
                    "name": "іржавий ніж",
                    "reason": "added_to_inventory_this_turn",
                }
            ],
        )

    def test_existing_inventory_item_entity_tag_is_not_stored_in_scene(self):
        class FakeNarrator:
            def narrate(self, player_input, session_state, on_token=None):
                return "Ти оглядаєш [[entity:item|old_compass|Old Compass|available|C]]."

        class FakeStore:
            def __init__(self):
                self.state = create_initial_game_state()

            def get_session(self):
                return self.state

        result = process_lite_turn("оглянути компас", RouteContext(FakeStore(), FakeNarrator()))

        self.assertFalse(any(entity["id"] == "old_compass" for entity in result["visible_state"]["scene"]["entities"]))
        self.assertEqual(result["debug"]["scene_entities_skipped_due_to_ownership"][0]["reason"], "already_in_inventory")
        self.assertIn("[[entity:item|old_compass|Old Compass|available|C]]", result["narrative_text"])

    def test_current_location_entity_tag_is_not_stored_in_scene(self):
        class FakeNarrator:
            def narrate(self, player_input, session_state, on_token=None):
                return "Ти стоїш на [[entity:place|stonemarket|ринок|available|P]]."

        class FakeStore:
            def __init__(self):
                self.state = create_initial_game_state()

            def get_session(self):
                return self.state

        result = process_lite_turn("де я", RouteContext(FakeStore(), FakeNarrator()))

        self.assertFalse(any(entity["id"] == "stonemarket" for entity in result["visible_state"]["scene"]["entities"]))
        self.assertEqual(result["debug"]["scene_entities_skipped_due_to_ownership"][0]["reason"], "current_location")

    def test_scene_change_removed_entity_is_not_readded_to_scene(self):
        class FakeNarrator:
            responses = [
                "Тут є [[entity:item|torch_01|смолоскип|available|T]].",
                (
                    "Смолоскип догорає. "
                    "[[entity:item|torch_01|смолоскип|available|T]] "
                    "[[scene_change|remove_entity:torch_01]]"
                ),
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
        result = process_lite_turn("чекати", RouteContext(store, narrator))

        self.assertFalse(any(entity["id"] == "torch_01" for entity in result["visible_state"]["scene"]["entities"]))
        self.assertEqual(result["debug"]["scene_entities_skipped_due_to_ownership"][0]["reason"], "removed_by_scene_change")

    def test_scene_change_removes_scene_entity_without_touching_inventory(self):
        class FakeNarrator:
            def narrate(self, player_input, session_state, on_token=None):
                return (
                    "Кераміка тріскає і лишає "
                    "[[entity:item|ceramic_shards_01|керамічні уламки|available|S]]. "
                    "[[scene_change|remove_entity:ceramic_01]]"
                )

        class FakeStore:
            def __init__(self):
                self.state = create_initial_game_state()
                self.state["scene"]["entities"].append(
                    {
                        "id": "ceramic_01",
                        "class": "item",
                        "name": "кераміка",
                        "visibility": "available",
                        "icon": "C",
                        "last_seen_turn": 1,
                    }
                )
                self.state["player"]["inventory"].append(
                    {"id": "ceramic_01", "name": "кишенькова кераміка", "icon": "C"}
                )

            def get_session(self):
                return self.state

        store = FakeStore()
        narrator = FakeNarrator()
        result = process_lite_turn("розбити", RouteContext(store, narrator))
        scene_ids = [entity["id"] for entity in result["visible_state"]["scene"]["entities"]]
        inventory_ids = [item["id"] for item in result["visible_state"]["player"]["inventory"]]

        self.assertNotIn("ceramic_01", scene_ids)
        self.assertIn("ceramic_shards_01", scene_ids)
        self.assertIn("ceramic_01", inventory_ids)
        self.assertNotIn("[[scene_change|remove_entity:ceramic_01]]", result["narrative_text"])
        self.assertEqual(result["debug"]["parsed_tags"]["scene_changes"][0]["command"], "remove_entity")
        self.assertEqual(result["debug"]["applied_changes"][0]["action"], "remove_entity")
        self.assertEqual(result["latest_change_summary"], [{"kind": "remove_entity", "text": "Зникло: кераміка"}])

    def test_strip_player_change_tags_keeps_entity_tags(self):
        text = (
            "Ти бачиш [[entity:npc|merchant_01|торговець|available|M]]. "
            "[[player_change|add_item:knife]]"
        )
        self.assertEqual(
            strip_player_change_tags(text),
            "Ти бачиш [[entity:npc|merchant_01|торговець|available|M]].",
        )

    def test_strip_player_change_tags_also_hides_scene_changes(self):
        text = (
            "Ти бачиш [[entity:item|ceramic_01|кераміка|available|C]]. "
            "[[scene_change|remove_entity:ceramic_01]]"
        )
        self.assertEqual(
            strip_player_change_tags(text),
            "Ти бачиш [[entity:item|ceramic_01|кераміка|available|C]].",
        )


if __name__ == "__main__":
    unittest.main()
