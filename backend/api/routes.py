"""Route-facing handlers for the tag-driven Lite API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.core.state import (
    DEFAULT_ICON,
    InMemorySessionStore,
    append_history_turn,
    build_messages,
    build_visible_state,
    detect_output_language,
    entity_to_currency,
    entity_to_inventory_item,
    entity_to_location,
    entity_to_skill,
)
from backend.core.tag_parser import parse_tags, strip_tags
from backend.llm.narrator import Narrator


@dataclass
class RouteContext:
    """Services required by the API route handlers."""

    session_store: InMemorySessionStore
    narrator: Narrator


def get_session_response(context: RouteContext) -> dict[str, Any]:
    """Return the current visible GameState."""

    game_state = context.session_store.get_session()
    return {
        "output_language": game_state.get("output_language", ""),
        "visible_state": build_visible_state(game_state),
        "recent_messages": build_messages(game_state),
        "history": list(game_state.get("history", [])),
        "debug": dict(game_state.get("debug", {})),
    }


def process_message_response(
    payload: dict[str, Any],
    context: RouteContext,
) -> dict[str, Any]:
    """Process a single player message through the tag-driven Lite flow."""

    raw_message = str(payload.get("message", "")).strip()

    if "session_state" in payload and isinstance(payload["session_state"], dict):
        context.session_store.replace_session(payload["session_state"])

    result = process_lite_turn(raw_message, context)
    return {
        "output_language": context.session_store.get_session().get("output_language", ""),
        **result,
    }


def process_lite_turn(
    raw_message: str,
    context: RouteContext,
    on_narration_chunk=None,
) -> dict[str, Any]:
    """Run: user input -> Narrator -> parse tags -> update state -> save history."""

    game_state = context.session_store.get_session()
    if not game_state.get("output_language"):
        game_state["output_language"] = detect_output_language(raw_message, fallback="uk")

    turn = int(game_state.get("turn_count", 0)) + 1
    game_state["turn_count"] = turn

    raw_llm_response = context.narrator.narrate(
        raw_message,
        game_state,
        on_token=on_narration_chunk,
    )
    parsed_tags = parse_tags(raw_llm_response)
    parsed_entities = [_entity_for_state(entity, turn) for entity in parsed_tags["entities"]]

    previous_entities = list(game_state.get("scene", {}).get("entities", []))
    game_state.setdefault("scene", {})["entities"] = parsed_entities
    game_state["scene"]["last_response"] = raw_llm_response

    applied_changes, skipped_changes = apply_player_changes(
        game_state=game_state,
        player_change_tags=parsed_tags["player_changes"],
        parsed_entities=parsed_entities,
        previous_entities=previous_entities,
    )
    malformed_or_skipped = parsed_tags["malformed_or_skipped_tags"] + skipped_changes
    narrator_response_clean = strip_tags(raw_llm_response)

    game_state["debug"] = {
        "raw_llm_response": raw_llm_response,
        "parsed_tags": {
            "entities": parsed_entities,
            "player_changes": parsed_tags["player_changes"],
        },
        "applied_changes": applied_changes,
        "malformed_or_skipped_tags": malformed_or_skipped,
    }
    append_history_turn(
        game_state,
        user_input=raw_message,
        narrator_response_clean=narrator_response_clean,
        parsed_entities=parsed_entities,
        applied_changes=applied_changes,
    )

    return {
        "result": dict(game_state["debug"]),
        "narrative_text": narrator_response_clean,
        "visible_state": build_visible_state(game_state),
        "recent_messages": build_messages(game_state),
        "history": list(game_state.get("history", [])),
        "debug": dict(game_state["debug"]),
    }


def apply_player_changes(
    game_state: dict[str, Any],
    player_change_tags: list[dict[str, Any]],
    parsed_entities: list[dict[str, Any]],
    previous_entities: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply known player_change tags without world-logic validation."""

    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    player = game_state.setdefault("player", {})
    player.setdefault("inventory", [])
    player.setdefault("currencies", [])
    player.setdefault("skills", [])
    previous_entities = previous_entities or []

    for tag in player_change_tags:
        command = str(tag.get("command", ""))
        args = list(tag.get("args", []))

        if command in {"add_item", "remove_item", "add_skill", "remove_skill", "set_location"} and len(args) != 1:
            skipped.append(_invalid(tag, "wrong_argument_count"))
            continue
        if command in {"add_currency", "remove_currency"} and len(args) != 2:
            skipped.append(_invalid(tag, "wrong_argument_count"))
            continue

        if command == "add_item":
            applied.append(_add_item(player, args[0], parsed_entities))
        elif command == "remove_item":
            applied.append(_remove_by_id(player["inventory"], args[0], "remove_item"))
        elif command == "add_currency":
            change, invalid = _add_currency(player, args[0], args[1], parsed_entities, previous_entities)
            (skipped if invalid else applied).append(change)
        elif command == "remove_currency":
            applied.append(_remove_currency(player, args[0], args[1]))
        elif command == "add_skill":
            applied.append(_add_skill(player, args[0], parsed_entities))
        elif command == "remove_skill":
            applied.append(_remove_by_id(player["skills"], args[0], "remove_skill"))
        elif command == "set_location":
            applied.append(_set_location(game_state, args[0], parsed_entities))

    return applied, skipped


def _entity_for_state(entity: dict[str, Any], turn: int) -> dict[str, Any]:
    entity_class = str(entity["class"])
    return {
        "id": str(entity["id"]),
        "class": entity_class,
        "name": str(entity["name"]),
        "visibility": str(entity["visibility"]),
        "icon": str(entity.get("icon") or DEFAULT_ICON.get(entity_class, "•")),
        "last_seen_turn": turn,
    }


def _add_item(player: dict[str, Any], item_id: str, entities: list[dict[str, Any]]) -> dict[str, Any]:
    inventory = player["inventory"]
    if not _find_by_id(inventory, item_id):
        entity = _find_entity(entities, item_id, "item") or _find_by_id(inventory, item_id) or {"id": item_id, "name": item_id}
        inventory.append(entity_to_inventory_item(entity, item_id))
    return {"action": "add_item", "id": item_id}


def _add_skill(player: dict[str, Any], skill_id: str, entities: list[dict[str, Any]]) -> dict[str, Any]:
    skills = player["skills"]
    if not _find_by_id(skills, skill_id):
        entity = _find_entity(entities, skill_id, "skill") or _find_by_id(skills, skill_id) or {"id": skill_id, "name": skill_id}
        skills.append(entity_to_skill(entity, skill_id))
    return {"action": "add_skill", "id": skill_id}


def _add_currency(
    player: dict[str, Any],
    currency_id: str,
    amount_text: str,
    entities: list[dict[str, Any]],
    previous_entities: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    amount = _to_int(amount_text)
    existing = _find_by_id(player["currencies"], currency_id)
    current_entity = _find_entity(entities, currency_id, "currency")
    previous_entity = _find_entity(previous_entities, currency_id, "currency")
    currency_source = current_entity or existing or previous_entity
    if currency_source is None:
        return _invalid({"raw": f"add_currency:{currency_id}:{amount_text}"}, "invalid_reference"), True
    if existing is None:
        existing = entity_to_currency(currency_source, amount=0)
        player["currencies"].append(existing)
    elif current_entity is not None:
        existing["name"] = current_entity.get("name", existing.get("name", currency_id))
        existing["icon"] = current_entity.get("icon", existing.get("icon", DEFAULT_ICON["currency"]))
    existing["amount"] = int(existing.get("amount", 0)) + amount
    return {"action": "add_currency", "id": currency_id, "amount": amount}, False


def _remove_currency(player: dict[str, Any], currency_id: str, amount_text: str) -> dict[str, Any]:
    amount = _to_int(amount_text)
    currency = _find_by_id(player["currencies"], currency_id)
    if currency is not None:
        currency["amount"] = max(0, int(currency.get("amount", 0)) - amount)
    return {"action": "remove_currency", "id": currency_id, "amount": amount}


def _set_location(game_state: dict[str, Any], location_id: str, entities: list[dict[str, Any]]) -> dict[str, Any]:
    current = game_state.setdefault("scene", {}).setdefault("location", {})
    entity = _find_entity(entities, location_id, "place")
    if entity is None and current.get("id") == location_id:
        entity = current
    if entity is None:
        entity = {"id": location_id, "name": location_id, "icon": DEFAULT_ICON["place"]}
    game_state["scene"]["location"] = entity_to_location(entity, location_id)
    return {"action": "set_location", "id": location_id}


def _remove_by_id(items: list[dict[str, Any]], item_id: str, action: str) -> dict[str, Any]:
    items[:] = [item for item in items if item.get("id") != item_id]
    return {"action": action, "id": item_id}


def _find_entity(entities: list[dict[str, Any]], entity_id: str, entity_class: str) -> dict[str, Any] | None:
    return next(
        (
            entity
            for entity in entities
            if entity.get("id") == entity_id and entity.get("class") == entity_class
        ),
        None,
    )


def _find_by_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("id") == item_id), None)


def _invalid(tag: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"raw": str(tag.get("raw", "")), "reason": reason}


def _to_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
