"""Focused checks for the Hyperlite state system."""

import json
import unittest

from backend.api.routes import RouteContext, apply_player_changes, process_hyperlite_turn
from backend.config import Settings
from backend.core.state import build_messages, create_initial_game_state, normalize_game_state
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
                "player": {"inventory": [], "resources": [], "currencies": [], "skills": []},
                "history": [],
                "output_language": "uk",
            },
        )
        prompt = json.loads(adapter.seen_prompt)

        self.assertNotIn("current_" + "loc" + "ation", prompt)
        self.assertNotIn("current_" + "scene_entities", prompt)
        self.assertIn("player_resources", prompt)
        self.assertIn("player_currencies", prompt)
        self.assertIn("player_skills", prompt)

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
                yield "Текст [[player_change|add_skill_progress|fire_control|"

        narrator = Narrator(FakeLLMAdapter())

        text = narrator.narrate("оглянутись", create_initial_game_state(), on_token=lambda chunk: None)

        self.assertTrue(narrator.last_diagnostics["has_unclosed_tag"])
        self.assertTrue(narrator.last_diagnostics["ends_inside_known_tag"])
        self.assertEqual(narrator.last_diagnostics["ends_inside_tag_kind"], "player_change")
        self.assertEqual(text, "Текст [[player_change|add_skill_progress|fire_control|")

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
            "[[player_change|add_skill_progress|fire_control|Контроль вогню|🔥|12]] "
            "[[player_change|remove_skill|fire_control]]"
        )

        self.assertEqual(
            [change["command"] for change in parsed["player_changes"]],
            ["add_item", "add_resource", "add_skill_progress", "remove_skill"],
        )
        self.assertEqual(parsed["player_changes"][2]["args"][0], "fire_control")
        self.assertEqual(
            [tag["reason"] for tag in parsed["malformed_or_skipped_tags"]],
            ["unknown_player_change", "unknown_tag", "unknown_tag"],
        )

    def test_item_and_resource_changes_merge_and_remove_zero_stacks(self):
        state = create_initial_game_state()
        parsed = parse_tags(
            "[[player_change|add_item|arrow|Arrow|➶|3]]"
            "[[player_change|add_item|arrow|Arrow|➶|2]]"
            "[[player_change|add_resource|mana|Mana|✦|5]]"
            "[[player_change|add_resource|mana|Mana|✦|7]]"
            "[[player_change|remove_item|arrow|9]]"
            "[[player_change|remove_resource|mana|Mana|✦|20]]"
        )

        applied, skipped, warnings, events = apply_player_changes(state, parsed["player_changes"])

        self.assertEqual(skipped, [])
        self.assertEqual(events, [])
        self.assertFalse(any(item["id"] == "arrow" for item in state["player"]["inventory"]))
        self.assertFalse(any(resource["id"] == "mana" for resource in state["player"]["resources"]))
        self.assertEqual([warning["operation"] for warning in warnings], ["remove_item", "remove_resource"])
        self.assertEqual([warning["removed_amount"] for warning in warnings], [5, 12])
        self.assertEqual([change["action"] for change in applied], ["add_item", "add_item", "add_resource", "add_resource", "remove_item", "remove_resource"])
        self.assertEqual([change.get("quantity") or change.get("amount") for change in applied[-2:]], [5, 12])

    def test_add_currency_creates_and_merges_without_duplicate(self):
        state = create_initial_game_state()
        parsed = parse_tags(
            "[[player_change|add_currency|gold|золото|💰|25]]"
            "[[player_change|add_currency|gold|інше золото|❌|10]]"
        )

        applied, skipped, warnings, events = apply_player_changes(state, parsed["player_changes"])

        currencies = [currency for currency in state["player"]["currencies"] if currency["id"] == "gold"]
        self.assertEqual(skipped, [])
        self.assertEqual(warnings, [])
        self.assertEqual(len(currencies), 1)
        self.assertEqual(currencies[0]["amount"], 35)
        self.assertEqual(currencies[0]["name"], "золото")
        self.assertEqual(currencies[0]["icon"], "💰")
        self.assertEqual([change["action"] for change in applied], ["add_currency", "add_currency"])

    def test_remove_currency_decreases_and_keeps_zero_currency(self):
        state = create_initial_game_state()
        state["player"]["currencies"].append({"id": "gold", "name": "золото", "icon": "💰", "amount": 25})

        applied, skipped, warnings, events = apply_player_changes(
            state,
            parse_tags(
                "[[player_change|remove_currency|gold|10]]"
                "[[player_change|remove_currency|gold|15]]"
            )["player_changes"],
        )

        gold = next(currency for currency in state["player"]["currencies"] if currency["id"] == "gold")
        self.assertEqual(gold["amount"], 0)
        self.assertEqual(warnings, [])
        self.assertEqual([change["amount"] for change in applied], [10, 15])

    def test_excessive_remove_currency_sets_zero_and_warns_actual_removed(self):
        state = create_initial_game_state()
        state["player"]["currencies"].append({"id": "gold", "name": "золото", "icon": "💰", "amount": 3})

        applied, skipped, warnings, events = apply_player_changes(
            state,
            parse_tags("[[player_change|remove_currency|gold|10]]")["player_changes"],
        )

        gold = next(currency for currency in state["player"]["currencies"] if currency["id"] == "gold")
        self.assertEqual(gold["amount"], 0)
        self.assertEqual(applied[0]["amount"], 3)
        self.assertEqual(warnings[0]["operation"], "remove_currency")
        self.assertEqual(warnings[0]["requested_amount"], 10)
        self.assertEqual(warnings[0]["removed_amount"], 3)

    def test_remove_missing_currency_is_noop_with_warning(self):
        state = create_initial_game_state()
        before = list(state["player"]["currencies"])

        applied, skipped, warnings, events = apply_player_changes(
            state,
            parse_tags("[[player_change|remove_currency|gems|5]]")["player_changes"],
        )

        self.assertEqual(state["player"]["currencies"], before)
        self.assertEqual(applied, [])
        self.assertEqual(warnings[0]["operation"], "remove_currency")
        self.assertEqual(warnings[0]["reason"], "unknown_target")

    def test_invalid_currency_amount_does_not_change_state(self):
        state = create_initial_game_state()
        before = list(state["player"]["currencies"])
        parsed = parse_tags("[[player_change|add_currency|gold|золото|💰|NaN]]")

        applied, skipped, warnings, events = apply_player_changes(state, parsed["player_changes"])

        self.assertEqual(state["player"]["currencies"], before)
        self.assertEqual(applied, [])
        self.assertEqual(skipped[0]["reason"], "invalid_amount")
        self.assertEqual(warnings[0]["operation"], "add_currency")

    def test_valid_remove_resource_parses_updates_state_and_creates_loss_event(self):
        state = create_initial_game_state()
        state["player"]["resources"].append({"id": "stone", "name": "камінці", "icon": "🪨", "amount": 8})

        result = process_hyperlite_turn("викидаю", RouteContext(_FakeStore(state), _FakeNarrator(
            "Ти викидаєш камінці.\n[[player_change|remove_resource|stone|камінці|🪨|5]]"
        )))

        stone = next(resource for resource in result["visible_state"]["player"]["resources"] if resource["id"] == "stone")
        self.assertEqual(stone["amount"], 3)
        self.assertEqual(result["debug"]["parsed_tags"]["player_changes"][0]["command"], "remove_resource")
        self.assertEqual(result["recent_messages"][-1]["change_summary"][0]["text"], "Втрачено: камінці x5")
        self.assertNotIn("[[player_change", result["narrative_text"])

    def test_excessive_remove_resource_removes_only_available_and_deletes_zero_stack(self):
        state = create_initial_game_state()
        state["player"]["resources"].append({"id": "stone", "name": "камінці", "icon": "🪨", "amount": 3})

        applied, skipped, warnings, events = apply_player_changes(
            state,
            parse_tags("[[player_change|remove_resource|stone|камінці|🪨|5]]")["player_changes"],
        )

        self.assertFalse(any(resource["id"] == "stone" for resource in state["player"]["resources"]))
        self.assertEqual(applied[0]["amount"], 3)
        self.assertEqual(warnings[0]["operation"], "remove_resource")
        self.assertEqual(warnings[0]["requested_amount"], 5)
        self.assertEqual(warnings[0]["removed_amount"], 3)

    def test_remove_unknown_resource_has_warning_and_no_success_event(self):
        state = create_initial_game_state()

        result = process_hyperlite_turn("викидаю", RouteContext(_FakeStore(state), _FakeNarrator(
            "Немає камінців.\n[[player_change|remove_resource|stone|камінці|🪨|5]]"
        )))

        self.assertEqual(result["debug"]["applied_changes"], [])
        self.assertEqual(result["latest_change_summary"], [])
        self.assertEqual(result["debug"]["warnings"][0]["reason"], "unknown_target")

    def test_remove_item_actual_amount_and_zero_cleanup(self):
        state = create_initial_game_state()
        state["player"]["inventory"].append({"id": "steel_sword", "name": "сталевий меч", "icon": "⚔️", "quantity": 1})

        applied, skipped, warnings, events = apply_player_changes(
            state,
            parse_tags("[[player_change|remove_item|steel_sword|5]]")["player_changes"],
        )

        self.assertFalse(any(item["id"] == "steel_sword" for item in state["player"]["inventory"]))
        self.assertEqual(applied[0]["quantity"], 1)
        self.assertEqual(warnings[0]["requested_amount"], 5)
        self.assertEqual(warnings[0]["removed_amount"], 1)

    def test_process_turn_item_remove_event_uses_actual_removed_quantity(self):
        state = create_initial_game_state()
        state["player"]["inventory"].append({"id": "steel_sword", "name": "сталевий меч", "icon": "⚔️", "quantity": 1})

        result = process_hyperlite_turn("ламаю меч", RouteContext(_FakeStore(state), _FakeNarrator(
            "Меч втрачено.\n[[player_change|remove_item|steel_sword|5]]"
        )))

        self.assertEqual(result["recent_messages"][-1]["change_summary"][0]["text"], "Втрачено: сталевий меч x1")

    def test_normalize_preserves_zero_currency_and_removes_zero_items_resources(self):
        normalized = normalize_game_state(
            {
                "player": {
                    "inventory": [{"id": "arrow", "name": "Arrow", "icon": "➶", "quantity": 0}],
                    "resources": [{"id": "stone", "name": "камінці", "icon": "🪨", "amount": 0}],
                    "currencies": [{"id": "gold", "name": "золото", "icon": "💰", "amount": 0}],
                    "skills": [],
                }
            }
        )

        self.assertEqual(normalized["player"]["inventory"], [])
        self.assertEqual(normalized["player"]["resources"], [])
        self.assertEqual(normalized["player"]["currencies"], [{"id": "gold", "name": "золото", "icon": "💰", "amount": 0}])

    def test_updated_resource_state_survives_save_load_normalization(self):
        state = create_initial_game_state()
        state["player"]["resources"].append({"id": "stone", "name": "камінці", "icon": "🪨", "amount": 8})
        apply_player_changes(
            state,
            parse_tags("[[player_change|remove_resource|stone|камінці|🪨|5]]")["player_changes"],
        )

        normalized = normalize_game_state(state)

        self.assertEqual(normalized["player"]["resources"], [{"id": "stone", "name": "камінці", "icon": "🪨", "amount": 3}])

    def test_new_skill_gets_progress_but_remains_level_zero(self):
        state = create_initial_game_state()
        applied, skipped, warnings, events = apply_player_changes(
            state,
            parse_tags("[[player_change|add_skill_progress|fire_control|Контроль вогню|🔥|12]]")["player_changes"],
        )

        skill = _find_skill(state, "fire_control")
        self.assertEqual(skipped, [])
        self.assertEqual(warnings, [])
        self.assertEqual(skill["level"], 0)
        self.assertEqual(skill["progress"], 12)
        self.assertEqual(applied[0]["action"], "add_skill_progress")
        self.assertEqual(events[0]["previousLevel"], 0)
        self.assertEqual(events[0]["newLevel"], 0)

    def test_level_zero_skill_is_not_in_recent_player_sheet_messages_but_is_in_debug(self):
        class FakeNarrator:
            last_diagnostics = {"model": "fake-model"}

            def narrate(self, player_input, session_state, on_token=None):
                return "Ти відчуваєш жар.\n[[player_change|add_skill_progress|fire_control|Контроль вогню|🔥|12]]"

        class FakeStore:
            def __init__(self):
                self.state = create_initial_game_state()

            def get_session(self):
                return self.state

        result = process_hyperlite_turn("тренуюсь", RouteContext(FakeStore(), FakeNarrator()))

        visible_skills = [skill for skill in result["visible_state"]["player"]["skills"] if skill.get("level", 0) > 0]
        self.assertFalse(any(skill["id"] == "fire_control" for skill in visible_skills))
        self.assertTrue(any(skill["id"] == "fire_control" and skill["level"] == 0 for skill in result["debug"]["player_skills"]))

    def test_progress_moves_level_zero_skill_to_level_one(self):
        state = create_initial_game_state()
        state["player"]["skills"].append({"id": "fire_control", "name": "Контроль вогню", "icon": "🔥", "level": 0, "progress": 92})

        applied, skipped, warnings, events = apply_player_changes(
            state,
            parse_tags("[[player_change|add_skill_progress|fire_control|Контроль вогню|🔥|12]]")["player_changes"],
        )

        skill = _find_skill(state, "fire_control")
        self.assertEqual(skill["level"], 1)
        self.assertEqual(skill["progress"], 4)
        self.assertEqual(events[0]["previousLevel"], 0)
        self.assertEqual(events[0]["newLevel"], 1)
        self.assertEqual(events[0]["levelsGained"], 1)

    def test_progress_without_level_up_updates_existing_skill(self):
        state = create_initial_game_state()
        state["player"]["skills"].append({"id": "fire_control", "name": "Контроль вогню", "icon": "🔥", "level": 1, "progress": 64})

        applied, skipped, warnings, events = apply_player_changes(
            state,
            parse_tags("[[player_change|add_skill_progress|fire_control|Інша назва|❌|12]]")["player_changes"],
        )

        skill = _find_skill(state, "fire_control")
        self.assertEqual(skill["name"], "Контроль вогню")
        self.assertEqual(skill["icon"], "🔥")
        self.assertEqual(skill["level"], 1)
        self.assertEqual(skill["progress"], 76)
        self.assertEqual(events[0]["previousProgress"], 64)
        self.assertEqual(events[0]["newProgress"], 76)

    def test_progress_overflow_levels_up_once(self):
        state = create_initial_game_state()
        state["player"]["skills"].append({"id": "fire_control", "name": "Контроль вогню", "icon": "🔥", "level": 1, "progress": 92})

        applied, skipped, warnings, events = apply_player_changes(
            state,
            parse_tags("[[player_change|add_skill_progress|fire_control|Контроль вогню|🔥|25]]")["player_changes"],
        )

        skill = _find_skill(state, "fire_control")
        self.assertEqual(skill["level"], 2)
        self.assertEqual(skill["progress"], 17)
        self.assertEqual(events[0]["levelsGained"], 1)

    def test_large_increment_can_gain_multiple_levels(self):
        state = create_initial_game_state()
        state["player"]["skills"].append({"id": "fire_control", "name": "Контроль вогню", "icon": "🔥", "level": 0, "progress": 80})

        applied, skipped, warnings, events = apply_player_changes(
            state,
            parse_tags("[[player_change|add_skill_progress|fire_control|Контроль вогню|🔥|250]]")["player_changes"],
        )

        skill = _find_skill(state, "fire_control")
        self.assertEqual(skill["level"], 3)
        self.assertEqual(skill["progress"], 30)
        self.assertEqual(events[0]["levelsGained"], 3)

    def test_repeated_progress_tags_are_aggregated_by_skill_id(self):
        state = create_initial_game_state()
        parsed = parse_tags(
            "[[player_change|add_skill_progress|fire_control|Контроль вогню|🔥|12]]"
            "[[player_change|add_skill_progress|fire_control|Інша назва|❌|8]]"
        )

        applied, skipped, warnings, events = apply_player_changes(state, parsed["player_changes"])

        skill = _find_skill(state, "fire_control")
        self.assertEqual(skill["name"], "Контроль вогню")
        self.assertEqual(skill["icon"], "🔥")
        self.assertEqual(skill["progress"], 20)
        self.assertEqual(len([skill for skill in state["player"]["skills"] if skill["id"] == "fire_control"]), 1)
        self.assertEqual(events[0]["addedProgress"], 20)
        self.assertEqual(len(events), 1)

    def test_invalid_skill_progress_amount_does_not_change_state(self):
        state = create_initial_game_state()
        before = list(state["player"]["skills"])
        parsed = parse_tags("[[player_change|add_skill_progress|fire_control|Контроль вогню|🔥|NaN]]")

        applied, skipped, warnings, events = apply_player_changes(state, parsed["player_changes"])

        self.assertEqual(state["player"]["skills"], before)
        self.assertEqual(applied, [])
        self.assertEqual(events, [])
        self.assertEqual(skipped[0]["reason"], "invalid_amount")
        self.assertEqual(warnings[0]["reason"], "invalid_amount")

    def test_missing_skill_progress_fields_create_warning_in_turn_debug(self):
        class FakeNarrator:
            last_diagnostics = {"model": "fake-model"}

            def narrate(self, player_input, session_state, on_token=None):
                return "Текст [[player_change|add_skill_progress|fire_control|Контроль вогню|🔥]]"

        class FakeStore:
            def __init__(self):
                self.state = create_initial_game_state()

            def get_session(self):
                return self.state

        result = process_hyperlite_turn("тренуюсь", RouteContext(FakeStore(), FakeNarrator()))

        self.assertEqual(result["debug"]["applied_changes"], [])
        self.assertEqual(result["debug"]["warnings"][0]["action"], "add_skill_progress")
        self.assertEqual(result["debug"]["warnings"][0]["reason"], "malformed_player_change")

    def test_description_survives_progress_update(self):
        state = create_initial_game_state()
        state["player"]["skills"].append(
            {
                "id": "fire_control",
                "name": "Контроль вогню",
                "icon": "🔥",
                "level": 1,
                "progress": 10,
                "description": "Утримує невелике полум'я.",
            }
        )

        apply_player_changes(
            state,
            parse_tags("[[player_change|add_skill_progress|fire_control|Нове|❌|10]]")["player_changes"],
        )

        skill = _find_skill(state, "fire_control")
        self.assertEqual(skill["description"], "Утримує невелике полум'я.")
        self.assertEqual(skill["name"], "Контроль вогню")

    def test_raw_skill_progress_tag_is_hidden_from_narrative(self):
        class FakeNarrator:
            last_diagnostics = {"model": "fake-model"}

            def narrate(self, player_input, session_state, on_token=None):
                return "Ти тренуєш дихання.\n[[player_change|add_skill_progress|fire_control|Контроль вогню|🔥|12]]"

        class FakeStore:
            def __init__(self):
                self.state = create_initial_game_state()

            def get_session(self):
                return self.state

        result = process_hyperlite_turn("тренуюсь", RouteContext(FakeStore(), FakeNarrator()))
        assistant = result["recent_messages"][-1]

        self.assertEqual(result["narrative_text"], "Ти тренуєш дихання.")
        self.assertNotIn("[[player_change", assistant["text"])

    def test_transient_ui_event_contains_previous_and_new_values(self):
        state = create_initial_game_state()
        state["player"]["skills"].append({"id": "fire_control", "name": "Контроль вогню", "icon": "🔥", "level": 1, "progress": 92})

        applied, skipped, warnings, events = apply_player_changes(
            state,
            parse_tags("[[player_change|add_skill_progress|fire_control|Контроль вогню|🔥|25]]")["player_changes"],
        )

        self.assertEqual(
            events[0],
            {
                "type": "skill_progress",
                "skillId": "fire_control",
                "name": "Контроль вогню",
                "icon": "🔥",
                "previousLevel": 1,
                "previousProgress": 92,
                "addedProgress": 25,
                "newLevel": 2,
                "newProgress": 17,
                "levelsGained": 1,
            },
        )

    def test_skill_progress_persists_through_save_load_normalization(self):
        snapshot = {
            "player": {
                "inventory": [],
                "resources": [],
                "skills": [
                    {"id": "fire_control", "name": "Контроль вогню", "icon": "🔥", "level": 0, "progress": 64},
                    {
                        "id": "ember_touch",
                        "name": "Дотик іскри",
                        "icon": "✨",
                        "level": 2,
                        "progress": 17,
                        "description": "Запалює сухий трут.",
                    },
                ],
            },
            "history": [],
            "debug": {},
            "output_language": "uk",
        }

        normalized = normalize_game_state(snapshot)

        self.assertEqual(normalized["player"]["skills"], snapshot["player"]["skills"])

    def test_remove_skill_deletes_existing_unlocked_and_level_zero_skills(self):
        state = create_initial_game_state()
        state["player"]["skills"].append({"id": "fire_control", "name": "Контроль вогню", "icon": "🔥", "level": 0, "progress": 64})
        state["player"]["skills"].append({"id": "ember_touch", "name": "Дотик іскри", "icon": "✨", "level": 1, "progress": 10})

        applied, skipped, warnings, events = apply_player_changes(
            state,
            parse_tags(
                "[[player_change|remove_skill|fire_control]]"
                "[[player_change|remove_skill|ember_touch]]"
            )["player_changes"],
        )

        self.assertIsNone(_find_skill_or_none(state, "fire_control"))
        self.assertIsNone(_find_skill_or_none(state, "ember_touch"))
        self.assertEqual(warnings, [])
        self.assertEqual(events, [])
        self.assertEqual([change["action"] for change in applied], ["remove_skill", "remove_skill"])

    def test_remove_skill_missing_id_is_noop_with_warning(self):
        state = create_initial_game_state()
        before = list(state["player"]["skills"])

        applied, skipped, warnings, events = apply_player_changes(
            state,
            parse_tags("[[player_change|remove_skill|missing_skill]]")["player_changes"],
        )

        self.assertEqual(state["player"]["skills"], before)
        self.assertEqual(applied, [])
        self.assertEqual(events, [])
        self.assertEqual(warnings[0]["reason"], "skill_not_found")

    def test_remove_skill_then_add_new_skill_progress_level_one_without_lineage(self):
        state = create_initial_game_state()
        state["player"]["skills"].append({"id": "fire_control", "name": "Контроль вогню", "icon": "🔥", "level": 2, "progress": 40})
        parsed = parse_tags(
            "[[player_change|remove_skill|fire_control]]"
            "[[player_change|add_skill_progress|inferno_mastery|Влада над полум'ям|🔥|100]]"
        )

        applied, skipped, warnings, events = apply_player_changes(state, parsed["player_changes"])

        new_skill = _find_skill(state, "inferno_mastery")
        self.assertIsNone(_find_skill_or_none(state, "fire_control"))
        self.assertEqual(new_skill["level"], 1)
        self.assertEqual(new_skill["progress"], 0)
        self.assertNotIn("transformedFrom", new_skill)
        self.assertNotIn("derivedFrom", new_skill)
        self.assertEqual(events[0]["previousLevel"], 0)
        self.assertEqual(events[0]["newLevel"], 1)

    def test_transient_skill_progress_event_is_returned_but_not_persisted_in_history(self):
        state = create_initial_game_state()

        class FakeNarrator:
            last_diagnostics = {"model": "fake-model"}

            def narrate(self, player_input, session_state, on_token=None):
                return "Ти практикуєшся.\n[[player_change|add_skill_progress|fire_control|Контроль вогню|🔥|12]]"

        class FakeStore:
            def __init__(self, state):
                self.state = state

            def get_session(self):
                return self.state

        result = process_hyperlite_turn("тренуюсь", RouteContext(FakeStore(state), FakeNarrator()))
        messages = build_messages(state)

        self.assertEqual(result["recent_messages"][-1]["change_summary"][0]["type"], "skill_progress")
        self.assertNotIn("change_summary", messages[-1])
        self.assertNotIn("change_summary", state["history"][-1])

    def test_strip_tags_removes_all_service_tags_from_clean_history(self):
        legacy_entity_tag = "[[" + "entity:item|x|річ|available|I]]"
        legacy_scene_tag = "[[" + "scene" + "_change|remove_entity|y]]"
        self.assertEqual(
            strip_tags(
                f"Текст {legacy_entity_tag}\n"
                f"[[player_change|add_skill_progress|x|Річ|I|1]]{legacy_scene_tag}"
            ),
            "Текст",
        )

    def test_strip_player_change_tags_only_hides_mutation_tags(self):
        legacy_entity_tag = "[[" + "entity:item|fruit_basket|Кошик|available|🍎]]"
        text = (
            "Ти бачиш кошик. "
            "[[player_change|add_skill_progress|fire_control|Контроль вогню|🔥|12]] "
            f"{legacy_entity_tag}"
        )
        self.assertEqual(
            strip_player_change_tags(text),
            f"Ти бачиш кошик. {legacy_entity_tag}",
        )


def _find_skill(state, skill_id):
    skill = _find_skill_or_none(state, skill_id)
    if skill is None:
        raise AssertionError(f"Missing skill: {skill_id}")
    return skill


def _find_skill_or_none(state, skill_id):
    return next((skill for skill in state["player"]["skills"] if skill.get("id") == skill_id), None)


class _FakeNarrator:
    last_diagnostics = {"model": "fake-model"}

    def __init__(self, text):
        self.text = text

    def narrate(self, player_input, session_state, on_token=None):
        return self.text


class _FakeStore:
    def __init__(self, state):
        self.state = state

    def get_session(self):
        return self.state


if __name__ == "__main__":
    unittest.main()
