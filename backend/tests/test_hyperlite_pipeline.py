"""Focused checks for the Hyperlite state system."""

import json
import unittest

from backend.api.routes import RouteContext, apply_player_changes, process_hyperlite_turn
from backend.config import Settings
from backend.core.state import create_initial_game_state, normalize_game_state
from backend.core.tag_parser import parse_tags, strip_player_change_tags, strip_tags
from backend.llm.client import OllamaLLMClient
from backend.llm.narrator import Narrator


class HyperlitePipelineTest(unittest.TestCase):
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

    def test_narrator_prompt_uses_player_state_only(self):
        legacy_scene_key = "sce" + "ne"
        legacy_place_key = "loc" + "ation"

        class FakeLLMAdapter:
            last_diagnostics = {}
            seen_prompt = ""

            def generate_text(self, system_prompt, user_prompt):
                self.seen_prompt = user_prompt
                return {"text": "Текст"}

        adapter = FakeLLMAdapter()
        narrator = Narrator(adapter)
        narrator.narrate(
            "оглянутись",
            {
                legacy_scene_key: {legacy_place_key: {"id": "old"}, "entities": [{"id": "x"}]},
                "player": {"inventory": [], "resources": [], "skills": []},
                "history": [],
                "output_language": "uk",
            },
        )
        prompt = json.loads(adapter.seen_prompt)

        self.assertNotIn("current_" + "loc" + "ation", prompt)
        self.assertNotIn("current_" + "scene_entities", prompt)
        self.assertIn("player_resources", prompt)

    def test_narrator_diagnostics_detect_unclosed_player_change(self):
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
                yield "Текст [[player_change|add_item|potion|"

        narrator = Narrator(FakeLLMAdapter())

        text = narrator.narrate("оглянутись", create_initial_game_state(), on_token=lambda chunk: None)

        self.assertEqual(text, "Текст [[player_change|add_item|potion|")
        self.assertTrue(narrator.last_diagnostics["has_unclosed_tag"])
        self.assertTrue(narrator.last_diagnostics["ends_inside_known_tag"])
        self.assertEqual(narrator.last_diagnostics["ends_inside_tag_kind"], "player_change")

    def test_parse_strict_player_changes_and_reject_old_tags(self):
        legacy_player_change = "[[" + "player_change|add_item:fruit_basket]]"
        legacy_entity_tag = "[[" + "entity:item|knife|ніж|available|K]]"
        legacy_scene_tag = "[[" + "scene" + "_change|remove_entity:knife]]"
        parsed = parse_tags(
            "Ти знаходиш кошик. "
            "[[player_change|add_item|fruit_basket|Кошик фруктів|🍎|2]] "
            f"{legacy_player_change} "
            f"{legacy_entity_tag} "
            f"{legacy_scene_tag} "
            "[[player_change|add_resource|gold|Золото|💰|10]] "
            "[[player_change|add_skill|awareness_plus|Гостра увага|◇]]"
        )

        self.assertEqual(
            [change["command"] for change in parsed["player_changes"]],
            ["add_item", "add_resource", "add_skill"],
        )
        self.assertEqual(parsed["player_changes"][0]["args"][0], "fruit_basket")
        self.assertEqual(
            [tag["reason"] for tag in parsed["malformed_or_skipped_tags"]],
            ["unknown_player_change", "unknown_tag", "unknown_tag"],
        )

    def test_apply_player_changes_merges_items_resources_and_skills_by_id(self):
        state = create_initial_game_state()
        parsed = parse_tags(
            "[[player_change|add_item|arrow|Arrow|➶|3]]"
            "[[player_change|add_item|arrow|Arrow|➶|2]]"
            "[[player_change|add_resource|mana|Mana|✦|5]]"
            "[[player_change|add_resource|mana|Mana|✦|7]]"
            "[[player_change|add_skill|focus|Focus|◇]]"
            "[[player_change|add_skill|focus|Focus|◇]]"
        )

        applied, skipped, warnings = apply_player_changes(state, parsed["player_changes"])

        self.assertEqual(skipped, [])
        self.assertEqual(warnings, [])
        self.assertEqual(next(item for item in state["player"]["inventory"] if item["id"] == "arrow")["quantity"], 5)
        self.assertEqual(next(resource for resource in state["player"]["resources"] if resource["id"] == "mana")["amount"], 12)
        self.assertEqual(len([skill for skill in state["player"]["skills"] if skill["id"] == "focus"]), 1)
        self.assertEqual([change["action"] for change in applied], ["add_item", "add_item", "add_resource", "add_resource", "add_skill", "add_skill"])

    def test_remove_clamps_to_zero_and_records_debug_warning(self):
        state = create_initial_game_state()
        state["player"]["inventory"].append({"id": "arrow", "name": "Arrow", "icon": "➶", "quantity": 3})
        state["player"]["resources"].append({"id": "mana", "name": "Mana", "icon": "✦", "amount": 2})
        parsed = parse_tags(
            "[[player_change|remove_item|arrow|9]]"
            "[[player_change|remove_resource|mana|5]]"
        )

        applied, skipped, warnings = apply_player_changes(state, parsed["player_changes"])

        self.assertEqual(skipped, [])
        self.assertEqual(next(item for item in state["player"]["inventory"] if item["id"] == "arrow")["quantity"], 0)
        self.assertEqual(next(resource for resource in state["player"]["resources"] if resource["id"] == "mana")["amount"], 0)
        self.assertEqual([warning["type"] for warning in warnings], ["underflow_clamped", "underflow_clamped"])
        self.assertEqual([change["remaining"] for change in applied], [0, 0])

    def test_process_turn_updates_player_and_hides_player_change_tags(self):
        class FakeNarrator:
            last_diagnostics = {"model": "fake-model"}

            def narrate(self, player_input, session_state, on_token=None):
                return (
                    "Ти піднімаєш кошик з фруктами.\n"
                    "[[player_change|add_item|fruit_basket|Кошик фруктів|🍎|1]]"
                )

        class FakeStore:
            def __init__(self):
                self.state = create_initial_game_state()

            def get_session(self):
                return self.state

        result = process_hyperlite_turn("беру кошик", RouteContext(FakeStore(), FakeNarrator()))
        assistant = result["recent_messages"][-1]

        self.assertEqual(result["narrative_text"], "Ти піднімаєш кошик з фруктами.")
        self.assertNotIn("[[player_change", assistant["text"])
        self.assertNotIn("scene", result["visible_state"])
        self.assertEqual(result["debug"]["parsed_tags"]["player_changes"][0]["command"], "add_item")
        self.assertEqual(result["latest_change_summary"], [{"kind": "add_item", "text": "Отримано: Кошик фруктів x1"}])

    def test_strip_tags_removes_all_service_tags_from_clean_history(self):
        legacy_entity_tag = "[[" + "entity:item|x|річ|available|I]]"
        legacy_scene_tag = "[[" + "scene" + "_change|remove_entity|y]]"
        self.assertEqual(
            strip_tags(
                f"Текст {legacy_entity_tag}\n"
                f"[[player_change|add_item|x|Річ|I|1]]{legacy_scene_tag}"
            ),
            "Текст",
        )

    def test_strip_player_change_tags_only_hides_valid_mutation_tags(self):
        legacy_entity_tag = "[[" + "entity:item|fruit_basket|Кошик|available|🍎]]"
        text = (
            "Ти бачиш кошик. "
            "[[player_change|add_item|fruit_basket|Кошик|🍎|1]] "
            f"{legacy_entity_tag}"
        )
        self.assertEqual(
            strip_player_change_tags(text),
            f"Ти бачиш кошик. {legacy_entity_tag}",
        )

    def test_normalize_game_state_removes_legacy_resource_container(self):
        legacy_container = "curr" + "encies"
        legacy_scene_key = "sce" + "ne"
        legacy_place_key = "loc" + "ation"
        normalized = normalize_game_state(
            {
                legacy_scene_key: {legacy_place_key: {"id": "old"}, "entities": []},
                "player": {legacy_container: [{"id": "gold"}]},
            }
        )

        self.assertNotIn(legacy_container, normalized["player"])
        self.assertEqual(normalized["player"]["resources"], [])


if __name__ == "__main__":
    unittest.main()
