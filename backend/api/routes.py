"""Route-facing handlers for the Hyperlite API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.core.state import (
    InMemorySessionStore,
    append_history_turn,
    build_messages,
    build_visible_state,
    detect_output_language,
)
from backend.core.tag_parser import parse_tags, strip_player_change_tags, strip_tags
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
    """Process a single player message through the Hyperlite flow."""

    raw_message = str(payload.get("message", "")).strip()

    if "session_state" in payload and isinstance(payload["session_state"], dict):
        context.session_store.replace_session(payload["session_state"])

    result = process_hyperlite_turn(raw_message, context)
    return {
        "output_language": context.session_store.get_session().get("output_language", ""),
        **result,
    }


def process_hyperlite_turn(
    raw_message: str,
    context: RouteContext,
    on_narration_chunk=None,
) -> dict[str, Any]:
    """Run: user input -> Narrator -> parse player changes -> update player state."""

    game_state = context.session_store.get_session()
    if not game_state.get("output_language"):
        game_state["output_language"] = detect_output_language(raw_message, fallback="uk")

    raw_llm_response = context.narrator.narrate(
        raw_message,
        game_state,
        on_token=on_narration_chunk,
    )
    parsed_tags = parse_tags(raw_llm_response)
    applied_changes, skipped_changes, warnings = apply_player_changes(
        game_state=game_state,
        player_change_tags=parsed_tags["player_changes"],
    )
    malformed_or_skipped = parsed_tags["malformed_or_skipped_tags"] + skipped_changes
    narrator_response_for_ui = strip_player_change_tags(raw_llm_response)
    narrator_response_clean = strip_tags(raw_llm_response)
    latest_change_summary = build_change_summary(applied_changes)

    game_state["debug"] = {
        "raw_llm_response": raw_llm_response,
        "narrator_response_for_ui": narrator_response_for_ui,
        "llm_diagnostics": dict(getattr(context.narrator, "last_diagnostics", {}) or {}),
        "parsed_tags": {"player_changes": parsed_tags["player_changes"]},
        "applied_changes": applied_changes,
        "malformed_or_skipped_tags": malformed_or_skipped,
        "warnings": warnings,
    }
    append_history_turn(
        game_state,
        user_input=raw_message,
        narrator_response_for_ui=narrator_response_for_ui,
        narrator_response_clean=narrator_response_clean,
        applied_changes=applied_changes,
        change_summary=latest_change_summary,
    )

    return {
        "result": dict(game_state["debug"]),
        "narrative_text": narrator_response_for_ui,
        "visible_state": build_visible_state(game_state),
        "recent_messages": build_messages(game_state),
        "history": list(game_state.get("history", [])),
        "debug": dict(game_state["debug"]),
        "latest_change_summary": list(latest_change_summary),
    }


def build_change_summary(applied_changes: list[dict[str, Any]]) -> list[dict[str, str]]:
    summary: list[dict[str, str]] = []
    for change in applied_changes:
        action = change.get("action")
        name = str(change.get("name") or change.get("id") or "")
        amount = int(change.get("amount", 0) or 0)
        if action == "add_item":
            quantity = int(change.get("quantity", 0) or 0)
            summary.append({"kind": action, "text": f"Отримано: {name} x{quantity}"})
        elif action == "remove_item":
            quantity = int(change.get("quantity", 0) or 0)
            summary.append({"kind": action, "text": f"Втрачено: {name} x{quantity}"})
        elif action == "add_resource":
            summary.append({"kind": action, "text": f"Отримано: {amount} {name}"})
        elif action == "remove_resource":
            summary.append({"kind": action, "text": f"Витрачено: {amount} {name}"})
        elif action == "add_skill":
            summary.append({"kind": action, "text": f"Отримано навичку: {name}"})
        elif action == "remove_skill":
            summary.append({"kind": action, "text": f"Втрачено навичку: {name}"})
    return summary


def apply_player_changes(
    game_state: dict[str, Any],
    player_change_tags: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply strict Hyperlite player_change tags."""

    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    player = game_state.setdefault("player", {})
    player.setdefault("inventory", [])
    player.setdefault("resources", [])
    player.setdefault("skills", [])

    for tag in player_change_tags:
        command = str(tag.get("command", ""))
        args = list(tag.get("args", []))

        if command == "add_item":
            change, invalid = _add_item(player, args)
            (skipped if invalid else applied).append(change)
        elif command == "remove_item":
            change, warning = _remove_stack(player["inventory"], args, "quantity", "remove_item")
            applied.append(change)
            if warning:
                warnings.append(warning)
        elif command == "add_resource":
            change, invalid = _add_resource(player, args)
            (skipped if invalid else applied).append(change)
        elif command == "remove_resource":
            change, warning = _remove_stack(player["resources"], args, "amount", "remove_resource")
            applied.append(change)
            if warning:
                warnings.append(warning)
        elif command == "add_skill":
            applied.append(_add_skill(player, args))
        elif command == "remove_skill":
            applied.append(_remove_skill(player, args[0]))

    return applied, skipped, warnings


def _add_item(player: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], bool]:
    item_id, name, icon, quantity_text = args[0], args[1], args[2], args[3]
    quantity = _to_non_negative_int(quantity_text)
    if quantity <= 0:
        return _invalid({"raw": f"add_item:{item_id}"}, "invalid_quantity"), True
    inventory = player["inventory"]
    existing = _find_by_id(inventory, item_id)
    if existing is None:
        existing = {"id": item_id, "name": name, "icon": icon, "quantity": 0}
        inventory.append(existing)
    else:
        existing["name"] = name
        existing["icon"] = icon
    existing["quantity"] = int(existing.get("quantity", 0) or 0) + quantity
    return {"action": "add_item", "id": item_id, "name": name, "icon": icon, "quantity": quantity}, False


def _add_resource(player: dict[str, Any], args: list[str]) -> tuple[dict[str, Any], bool]:
    resource_id, name, icon, amount_text = args[0], args[1], args[2], args[3]
    amount = _to_non_negative_int(amount_text)
    if amount <= 0:
        return _invalid({"raw": f"add_resource:{resource_id}"}, "invalid_amount"), True
    resources = player["resources"]
    existing = _find_by_id(resources, resource_id)
    if existing is None:
        existing = {"id": resource_id, "name": name, "icon": icon, "amount": 0}
        resources.append(existing)
    else:
        existing["name"] = name
        existing["icon"] = icon
    existing["amount"] = int(existing.get("amount", 0) or 0) + amount
    return {
        "action": "add_resource",
        "id": resource_id,
        "name": name,
        "icon": icon,
        "amount": amount,
    }, False


def _add_skill(player: dict[str, Any], args: list[str]) -> dict[str, Any]:
    skill_id, name, icon = args[0], args[1], args[2]
    skills = player["skills"]
    existing = _find_by_id(skills, skill_id)
    if existing is None:
        skills.append({"id": skill_id, "name": name, "icon": icon})
    else:
        existing["name"] = name
        existing["icon"] = icon
    return {"action": "add_skill", "id": skill_id, "name": name, "icon": icon}


def _remove_skill(player: dict[str, Any], skill_id: str) -> dict[str, Any]:
    skills = player["skills"]
    existing = _find_by_id(skills, skill_id)
    name = existing.get("name", skill_id) if existing is not None else skill_id
    skills[:] = [skill for skill in skills if skill.get("id") != skill_id]
    return {"action": "remove_skill", "id": skill_id, "name": str(name)}


def _remove_stack(
    stacks: list[dict[str, Any]],
    args: list[str],
    amount_key: str,
    action: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    stack_id, amount_text = args[0], args[1]
    amount = _to_non_negative_int(amount_text)
    existing = _find_by_id(stacks, stack_id)
    name = existing.get("name", stack_id) if existing is not None else stack_id
    current_amount = int(existing.get(amount_key, 0) or 0) if existing is not None else 0
    new_amount = max(0, current_amount - amount)
    warning = None

    if existing is not None:
        existing[amount_key] = new_amount
    if amount > current_amount:
        warning = {
            "type": "underflow_clamped",
            "action": action,
            "id": stack_id,
            "requested": amount,
            "available": current_amount,
        }

    return {
        "action": action,
        "id": stack_id,
        "name": str(name),
        amount_key: amount,
        "remaining": new_amount,
    }, warning


def _find_by_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("id") == item_id), None)


def _invalid(tag: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"raw": str(tag.get("raw", "")), "reason": reason}


def _to_non_negative_int(value: str) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
