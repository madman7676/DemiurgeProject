"""Route-facing handlers for the Hyperlite API."""

from __future__ import annotations

from dataclasses import dataclass
import re
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


SKILL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


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
    applied_changes, skipped_changes, warnings, ui_events = apply_player_changes(
        game_state=game_state,
        player_change_tags=parsed_tags["player_changes"],
    )
    warnings = _parser_warnings(parsed_tags["malformed_or_skipped_tags"]) + warnings
    malformed_or_skipped = parsed_tags["malformed_or_skipped_tags"] + skipped_changes
    narrator_response_for_ui = strip_player_change_tags(raw_llm_response)
    narrator_response_clean = strip_tags(raw_llm_response)
    latest_change_summary = build_change_summary(applied_changes, ui_events)

    game_state["debug"] = {
        "raw_llm_response": raw_llm_response,
        "narrator_response_for_ui": narrator_response_for_ui,
        "llm_diagnostics": dict(getattr(context.narrator, "last_diagnostics", {}) or {}),
        "parsed_tags": {"player_changes": parsed_tags["player_changes"]},
        "applied_changes": applied_changes,
        "ui_events": ui_events,
        "player_skills": _debug_skills(game_state),
        "malformed_or_skipped_tags": malformed_or_skipped,
        "warnings": warnings,
    }
    append_history_turn(
        game_state,
        user_input=raw_message,
        narrator_response_for_ui=narrator_response_for_ui,
        narrator_response_clean=narrator_response_clean,
        applied_changes=applied_changes,
    )
    recent_messages = build_messages(game_state)
    if latest_change_summary and recent_messages and recent_messages[-1].get("role") == "assistant":
        recent_messages[-1]["change_summary"] = list(latest_change_summary)

    return {
        "result": dict(game_state["debug"]),
        "narrative_text": narrator_response_for_ui,
        "visible_state": build_visible_state(game_state),
        "recent_messages": recent_messages,
        "history": list(game_state.get("history", [])),
        "debug": dict(game_state["debug"]),
        "latest_change_summary": list(latest_change_summary),
    }


def build_change_summary(
    applied_changes: list[dict[str, Any]],
    ui_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
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
    summary.extend(ui_events or [])
    return summary


def apply_player_changes(
    game_state: dict[str, Any],
    player_change_tags: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply strict Hyperlite player_change tags."""

    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    ui_events: list[dict[str, Any]] = []
    skill_progress_groups: dict[str, dict[str, Any]] = {}
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
        elif command == "add_skill_progress":
            change, warning = _collect_skill_progress(skill_progress_groups, tag, args)
            if warning:
                skipped.append(change)
                warnings.append(warning)
        elif command == "remove_skill":
            change, warning = _remove_skill(player, args[0])
            if warning:
                warnings.append(warning)
            else:
                applied.append(change)

    progress_changes, progress_events, progress_warnings = _apply_skill_progress_groups(
        player,
        skill_progress_groups,
    )
    applied.extend(progress_changes)
    ui_events.extend(progress_events)
    warnings.extend(progress_warnings)

    return applied, skipped, warnings, ui_events


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


def _collect_skill_progress(
    groups: dict[str, dict[str, Any]],
    tag: dict[str, Any],
    args: list[str],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    skill_id, name, icon, amount_text = args[0], args[1], args[2], args[3]
    amount = _to_positive_int(amount_text)
    if not SKILL_ID_PATTERN.fullmatch(skill_id):
        warning = _skill_warning(tag, "invalid_skill_id", skill_id=skill_id)
        return _invalid(tag, "invalid_skill_id"), warning
    if amount is None:
        warning = _skill_warning(tag, "invalid_amount", skill_id=skill_id, amount=amount_text)
        return _invalid(tag, "invalid_amount"), warning

    group = groups.setdefault(
        skill_id,
        {
            "skill_id": skill_id,
            "name": name,
            "icon": icon,
            "amount": 0,
            "raw_tags": [],
        },
    )
    group["amount"] += amount
    group["raw_tags"].append(str(tag.get("raw", "")))
    return {}, None


def _apply_skill_progress_groups(
    player: dict[str, Any],
    groups: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    changes: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    skills = player.setdefault("skills", [])

    for group in groups.values():
        skill_id = str(group["skill_id"])
        added_progress = int(group["amount"])
        existing = _find_by_id(skills, skill_id)
        created = existing is None
        if existing is None:
            existing = {
                "id": skill_id,
                "name": str(group["name"]),
                "icon": str(group["icon"]),
                "level": 0,
                "progress": 0,
            }
            skills.append(existing)

        previous_level = _to_non_negative_int(existing.get("level", 0))
        previous_progress = min(99, _to_non_negative_int(existing.get("progress", 0)))
        new_level = previous_level
        new_progress = previous_progress + added_progress
        levels_gained = 0

        while new_progress >= 100:
            new_progress -= 100
            new_level += 1
            levels_gained += 1

        existing["level"] = new_level
        existing["progress"] = new_progress
        existing.setdefault("name", str(group["name"]))
        existing.setdefault("icon", str(group["icon"]))

        event = {
            "type": "skill_progress",
            "skillId": skill_id,
            "name": str(existing.get("name") or skill_id),
            "icon": str(existing.get("icon") or "*"),
            "previousLevel": previous_level,
            "previousProgress": previous_progress,
            "addedProgress": added_progress,
            "newLevel": new_level,
            "newProgress": new_progress,
            "levelsGained": levels_gained,
        }
        changes.append(
            {
                "action": "add_skill_progress",
                "id": skill_id,
                "name": event["name"],
                "icon": event["icon"],
                "amount": added_progress,
                "previous_level": previous_level,
                "previous_progress": previous_progress,
                "new_level": new_level,
                "new_progress": new_progress,
                "levels_gained": levels_gained,
                "created": created,
            }
        )
        events.append(event)

    return changes, events, warnings


def _remove_skill(player: dict[str, Any], skill_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    skills = player["skills"]
    existing = _find_by_id(skills, skill_id)
    if existing is None:
        warning = {
            "type": "skill_change_skipped",
            "action": "remove_skill",
            "id": skill_id,
            "reason": "skill_not_found",
        }
        return {}, warning
    name = existing.get("name", skill_id)
    skills[:] = [skill for skill in skills if skill.get("id") != skill_id]
    return {"action": "remove_skill", "id": skill_id, "name": str(name)}, None


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


def _parser_warnings(skipped_tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for tag in skipped_tags:
        raw = str(tag.get("raw", ""))
        if raw.startswith("player_change|add_skill_progress"):
            warnings.append(
                {
                    "type": "skill_change_skipped",
                    "action": "add_skill_progress",
                    "raw": raw,
                    "reason": str(tag.get("reason", "invalid_skill_progress_tag")),
                }
            )
    return warnings


def _skill_warning(
    tag: dict[str, Any],
    reason: str,
    **details: Any,
) -> dict[str, Any]:
    warning = {
        "type": "skill_change_skipped",
        "action": str(tag.get("command", "")),
        "raw": str(tag.get("raw", "")),
        "reason": reason,
    }
    warning.update(details)
    return warning


def _debug_skills(game_state: dict[str, Any]) -> list[dict[str, Any]]:
    skills = game_state.get("player", {}).get("skills", [])
    if not isinstance(skills, list):
        return []
    debug_skills: list[dict[str, Any]] = []
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        item = {
            "id": str(skill.get("id", "")),
            "name": str(skill.get("name", "")),
            "icon": str(skill.get("icon", "")),
            "level": _to_non_negative_int(skill.get("level", 0)),
            "progress": min(99, _to_non_negative_int(skill.get("progress", 0))),
        }
        if skill.get("description"):
            item["description"] = str(skill["description"])
        debug_skills.append(item)
    return debug_skills


def _to_non_negative_int(value: str) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _to_positive_int(value: str) -> int | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d+", value.strip()):
        return None
    amount = int(value)
    if amount <= 0:
        return None
    return amount
