"""Route-facing handlers for the Lite exploration API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.core.scene_memory import apply_scene_memory, find_scene_entity
from backend.core.state import (
    InMemorySessionStore,
    append_message,
    build_visible_state,
    detect_output_language,
)
from backend.core.tag_parser import parse_tags
from backend.llm.narrator import Narrator


@dataclass
class RouteContext:
    """Services required by the API route handlers."""

    session_store: InMemorySessionStore
    narrator: Narrator


def get_session_response(context: RouteContext) -> dict[str, Any]:
    """Return the current visible in-memory session state."""

    session_state = context.session_store.get_session()
    return {
        "session_id": session_state["session_id"],
        "output_language": session_state.get("output_language", ""),
        "visible_state": build_visible_state(session_state),
        "recent_messages": list(session_state["recent_messages"]),
        "decision_history": list(session_state["decision_history"]),
    }


def process_message_response(
    payload: dict[str, Any],
    context: RouteContext,
) -> dict[str, Any]:
    """Process a single player message through the Lite pipeline."""

    raw_message = str(payload.get("message", "")).strip()

    if "session_state" in payload and isinstance(payload["session_state"], dict):
        context.session_store.replace_session(payload["session_state"])

    result = process_lite_turn(raw_message, context)
    return {
        "session_id": context.session_store.get_session()["session_id"],
        "output_language": context.session_store.get_session().get("output_language", ""),
        **result,
    }


def process_lite_turn(
    raw_message: str,
    context: RouteContext,
    on_narration_chunk=None,
) -> dict[str, Any]:
    """Run the direct Lite flow: user input -> Narrator -> tags -> state."""

    session_state = context.session_store.get_session()
    if not session_state.get("output_language"):
        session_state["output_language"] = detect_output_language(raw_message, fallback="uk")

    turn = int(session_state.get("turn_count", 0)) + 1
    session_state["turn_count"] = turn

    raw_llm_response = context.narrator.narrate(
        raw_message,
        session_state,
        on_token=on_narration_chunk,
    )
    parsed_tags = parse_tags(raw_llm_response)
    scene_changes = apply_scene_memory(session_state, parsed_tags["entities"])
    player_changes = apply_player_changes(session_state, parsed_tags["player_changes"])
    applied_changes = scene_changes + player_changes
    change_summary = [
        {"kind": change.get("kind", change.get("action", "change")), "text": change["summary"]}
        for change in applied_changes
        if change.get("summary")
    ]

    debug_event = {
        "source": "lite_pipeline",
        "message": "Narrator response parsed and applied.",
        "details": {
            "raw_llm_response": raw_llm_response,
            "parsed_tags": parsed_tags,
            "applied_changes": applied_changes,
        },
    }
    decision_cycle = {
        "turn": turn,
        "raw_player_input": raw_message,
        "events": [debug_event],
    }
    session_state.setdefault("decision_history", []).append(decision_cycle)
    append_message(session_state, "player", raw_message)
    append_message(session_state, "assistant", raw_llm_response, change_summary=change_summary)

    return {
        "result": {
            "raw_llm_response": raw_llm_response,
            "parsed_tags": parsed_tags,
            "applied_changes": applied_changes,
        },
        "narrative_text": raw_llm_response,
        "visible_state": build_visible_state(session_state),
        "recent_messages": list(session_state["recent_messages"]),
        "decision_cycle": decision_cycle,
        "decision_history": list(session_state["decision_history"]),
    }


def apply_player_changes(
    session_state: dict[str, Any],
    player_change_tags: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply player_change tags directly, without validation or rejection."""

    applied: list[dict[str, Any]] = []
    player_state = session_state.setdefault("player_state", {})

    for tag in player_change_tags:
        change = str(tag.get("change", "")).strip()
        command, _, value = change.partition(":")
        command = command.strip()
        value = value.strip()

        if command == "add_item" and value:
            applied.append(_add_item(player_state, session_state, value))
        elif command == "remove_item" and value:
            applied.append(_remove_item(player_state, value))
        elif command in {"add_gold", "add_coin"}:
            amount = _to_int(value)
            applied.append(_add_currency(player_state, "coin", "Coin", amount))
        elif command == "set_gold":
            amount = _to_int(value)
            applied.append(_set_currency(player_state, "coin", "Coin", amount))
        elif command == "add_skill" and value:
            skills = player_state.setdefault("skills", [])
            existing = next((skill for skill in skills if skill.get("skill_id") == value), None)
            if existing is None:
                skills.append({"skill_id": value, "name": value.replace("_", " ").title(), "level": 1})
            applied.append(
                {
                    "kind": "player_change",
                    "action": "add_skill",
                    "skill_id": value,
                    "summary": f"Added skill: {value}.",
                }
            )
        elif command:
            applied.append(
                {
                    "kind": "player_change",
                    "action": command,
                    "value": value,
                    "summary": f"Applied player change: {change}.",
                }
            )

    return applied


def _add_item(player_state: dict[str, Any], session_state: dict[str, Any], item_id: str) -> dict[str, Any]:
    inventory = player_state.setdefault("inventory", [])
    existing = next((item for item in inventory if item.get("item_id") == item_id), None)
    scene_entity = find_scene_entity(session_state, item_id) or {}
    item_name = str(scene_entity.get("name") or item_id.replace("_", " ").title())
    if existing is None:
        inventory.append({"item_id": item_id, "name": item_name, "quantity": 1, "aliases": []})
    else:
        existing["quantity"] = int(existing.get("quantity", 1)) + 1
    return {
        "kind": "player_change",
        "action": "add_item",
        "item_id": item_id,
        "summary": f"Added item: {item_name}.",
    }


def _remove_item(player_state: dict[str, Any], item_id: str) -> dict[str, Any]:
    inventory = player_state.setdefault("inventory", [])
    for item in list(inventory):
        if item.get("item_id") != item_id:
            continue
        quantity = int(item.get("quantity", 1)) - 1
        if quantity <= 0:
            inventory.remove(item)
        else:
            item["quantity"] = quantity
        break
    return {
        "kind": "player_change",
        "action": "remove_item",
        "item_id": item_id,
        "summary": f"Removed item: {item_id}.",
    }


def _add_currency(player_state: dict[str, Any], currency_id: str, name: str, amount: int) -> dict[str, Any]:
    currency = _currency(player_state, currency_id, name)
    currency["amount"] = int(currency.get("amount", 0)) + amount
    return {
        "kind": "player_change",
        "action": "add_gold",
        "amount": amount,
        "summary": f"Gold changed by {amount}.",
    }


def _set_currency(player_state: dict[str, Any], currency_id: str, name: str, amount: int) -> dict[str, Any]:
    currency = _currency(player_state, currency_id, name)
    currency["amount"] = amount
    return {
        "kind": "player_change",
        "action": "set_gold",
        "amount": amount,
        "summary": f"Gold set to {amount}.",
    }


def _currency(player_state: dict[str, Any], currency_id: str, name: str) -> dict[str, Any]:
    currencies = player_state.setdefault("currencies", [])
    existing = next((currency for currency in currencies if currency.get("currency_id") == currency_id), None)
    if existing is not None:
        return existing
    created = {"currency_id": currency_id, "name": name, "amount": 0, "aliases": ["gold"]}
    currencies.append(created)
    return created


def _to_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
