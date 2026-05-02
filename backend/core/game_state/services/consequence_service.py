"""Build minimal structured consequences for exploration actions."""

from __future__ import annotations

from copy import deepcopy
import logging
from random import Random
from typing import Any

from backend.core.game_state.contracts import GameSessionState
from backend.modules.narrator.services.narrator_service import normalize_scene_memory_name
from backend.core.npc_state.services.local_reaction_service import (
    build_local_npc_reactions,
)
from backend.core.game_state.services.quality_side_effects import (
    clamp_outcome_quality,
    quality_side_effect_chance,
    should_apply_quality_side_effect,
)
from backend.modules.action_evaluation.schemas.action_evaluation_contracts import (
    ActionProcessingContract,
)

logger = logging.getLogger(__name__)


def apply_consequence_layer(
    session_state: GameSessionState,
    action_result: ActionProcessingContract,
    action_category: str,
) -> ActionProcessingContract:
    """Attach lightweight consequences before persistent state updates."""

    updated_result = deepcopy(action_result)
    _resolve_quality_side_effects(session_state, updated_result)
    transfer_debug = _apply_entity_transfers(session_state, updated_result)
    mutation_debug = _apply_state_mutations(session_state, updated_result)
    applied_changes = transfer_debug["applied_changes"] + mutation_debug["applied_changes"]
    updated_result["applied_changes"] = applied_changes
    updated_result["change_summary"] = _build_change_summary(applied_changes)
    updated_result["consequence_debug"] = {
        "entity_transfers": transfer_debug,
        "state_mutations": mutation_debug,
    }
    npc_reactions = build_local_npc_reactions(
        raw_player_input=updated_result["raw_player_input"],
        action_category=action_category,
        nearby_npcs=session_state["npc_states"],
        player_location=session_state["player_state"]["current_location"],
    )
    updated_result["npc_reactions"] = npc_reactions

    updated_result["outcome_summary"] = _build_outcome_summary(updated_result, action_category)
    if action_category == "combat_attempt":
        updated_result["narration_notes"].append(
            "Acknowledge the attempted aggression without entering combat mode."
        )

    logger.info(
        "Consequences applied: transfers=%s mutations=%s applied=%s skipped=%s summary=%s outcome=%s",
        updated_result["state_intents"].get("entity_transfers", []),
        _mutation_intents(updated_result),
        applied_changes,
        transfer_debug["skipped_changes"] + mutation_debug["skipped_changes"],
        updated_result["change_summary"],
        updated_result["outcome_summary"],
    )
    return updated_result


def _apply_entity_transfers(
    session_state: GameSessionState,
    action_result: ActionProcessingContract,
) -> dict[str, Any]:
    """Validate and apply Judge-proposed entity moves between existing containers."""

    transfer_intents = list(action_result.get("state_intents", {}).get("entity_transfers", []))
    debug: dict[str, Any] = {
        "received_intents": transfer_intents,
        "applied_changes": [],
        "skipped_changes": [],
        "validation": [],
        "container_summary": {},
    }
    for transfer in transfer_intents:
        outcome = _apply_single_transfer(session_state, transfer)
        debug["validation"].append(outcome)
        if outcome["applied"]:
            debug["applied_changes"].append(outcome["change"])
        else:
            debug["skipped_changes"].append(
                {
                    "intent": transfer,
                    "reason": outcome["reason"],
                }
            )
    debug["container_summary"] = _container_summary(session_state)
    return debug


def _apply_single_transfer(
    session_state: GameSessionState,
    transfer: dict[str, Any],
) -> dict[str, Any]:
    source_name = str(transfer.get("from", "")).strip()
    target_name = str(transfer.get("to", "")).strip()
    entity_id = str(transfer.get("entity_id", "")).strip()
    entity_type = str(transfer.get("entity_type", "item")).strip() or "item"
    try:
        quantity = max(1, int(transfer.get("quantity", 1)))
    except (TypeError, ValueError):
        quantity = 1

    if source_name not in {"scene_pool", "inventory", "equipped"}:
        return _skipped_transfer(transfer, "Unsupported source container.")
    if target_name not in {"scene_pool", "inventory", "equipped"}:
        return _skipped_transfer(transfer, "Unsupported target container.")
    if not entity_id:
        return _skipped_transfer(transfer, "Missing entity_id.")
    if source_name == target_name:
        return _skipped_transfer(transfer, "Source and target containers are identical.")

    source_entry = _find_in_container(session_state, source_name, entity_id)
    if source_entry is None:
        return _skipped_transfer(transfer, f"Entity {entity_id} does not exist in {source_name}.")

    if _is_actor_like(entity_type, source_entry) and target_name in {"inventory", "equipped"}:
        return _skipped_transfer(transfer, "Actors/NPCs cannot be moved into inventory or equipped.")
    if source_name == "scene_pool" and source_entry.get("status") == "background":
        return _skipped_transfer(transfer, "Background scene entities are not transferable in this phase.")
    if source_name == "scene_pool" and str(source_entry.get("status", "available")) not in {"available", ""}:
        return _skipped_transfer(transfer, "Scene entity is not available for transfer.")
    if entity_type in {"skill", "currency"}:
        return _skipped_transfer(transfer, "Skills and currencies are not transferable in this phase.")

    available_quantity = int(source_entry.get("quantity", 1) or 1)
    if source_name in {"inventory", "equipped"} and quantity > available_quantity:
        return _skipped_transfer(transfer, "Requested quantity exceeds available quantity.")

    _remove_from_container(session_state, source_name, entity_id, quantity)
    target_entry = _build_target_entry(
        source_entry=source_entry,
        entity_id=entity_id,
        entity_type=entity_type,
        target_name=target_name,
        quantity=quantity,
        session_state=session_state,
    )
    _add_to_container(session_state, target_name, target_entry, quantity)
    _remove_duplicate_presence(session_state, entity_id, target_name)
    _sync_equipped_views(session_state)

    display_name = str(source_entry.get("name", source_entry.get("canonical_name", entity_id))).strip() or entity_id
    label = _summary_label(source_name, target_name)
    change = {
        "type": "entity_transfer",
        "entity_id": entity_id,
        "entity_name": display_name,
        "entity_type": entity_type,
        "from": source_name,
        "to": target_name,
        "quantity": quantity,
        "summary_label": label,
        "display_name": display_name,
    }
    return {
        "applied": True,
        "reason": "",
        "intent": transfer,
        "change": change,
    }


def _skipped_transfer(transfer: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "applied": False,
        "reason": reason,
        "intent": transfer,
        "change": None,
    }


def _find_in_container(
    session_state: GameSessionState,
    container_name: str,
    entity_id: str,
) -> dict[str, Any] | None:
    for entry in _container_entries(session_state, container_name):
        if _entry_id(entry, container_name) == entity_id:
            return entry
    return None


def _container_entries(
    session_state: GameSessionState,
    container_name: str,
) -> list[dict[str, Any]]:
    player_state = session_state["player_state"]
    if container_name == "scene_pool":
        return _get_scene_pool(session_state)
    if container_name == "inventory":
        return player_state.setdefault("inventory", [])
    equipped = player_state.setdefault("equipped_items", [])
    held = player_state.setdefault("held_items", [])
    combined: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in equipped + held:
        entry_id = _entry_id(entry, "equipped")
        if not entry_id or entry_id in seen_ids:
            continue
        seen_ids.add(entry_id)
        combined.append(entry)
    return combined


def _entry_id(entry: dict[str, Any], container_name: str) -> str:
    if container_name == "scene_pool":
        return str(entry.get("entity_id", entry.get("item_id", "")))
    return str(entry.get("item_id", entry.get("entity_id", "")))


def _remove_from_container(
    session_state: GameSessionState,
    container_name: str,
    entity_id: str,
    quantity: int,
) -> None:
    entries = _container_entries(session_state, container_name)
    kept: list[dict[str, Any]] = []
    for entry in entries:
        if _entry_id(entry, container_name) != entity_id:
            kept.append(entry)
            continue
        current_quantity = int(entry.get("quantity", 1) or 1)
        remaining_quantity = current_quantity - quantity
        if remaining_quantity > 0:
            updated = deepcopy(entry)
            updated["quantity"] = remaining_quantity
            kept.append(updated)
    _set_container_entries(session_state, container_name, kept)


def _add_to_container(
    session_state: GameSessionState,
    container_name: str,
    entry: dict[str, Any],
    quantity: int,
) -> None:
    entries = _container_entries(session_state, container_name)
    entry_id = _entry_id(entry, container_name)
    existing = next((item for item in entries if _entry_id(item, container_name) == entry_id), None)
    if existing is not None:
        if "quantity" in existing or "quantity" in entry:
            existing["quantity"] = int(existing.get("quantity", 1) or 1) + quantity
        if container_name == "scene_pool":
            existing["status"] = "available"
            existing["truth_status"] = existing.get("truth_status", "soft_scene")
            existing["last_seen_turn"] = session_state.get("turn_count", 0) + 1
            existing["mention_count"] = int(existing.get("mention_count", 0)) + 1
        return
    entries.append(entry)
    _set_container_entries(session_state, container_name, entries)


def _set_container_entries(
    session_state: GameSessionState,
    container_name: str,
    entries: list[dict[str, Any]],
) -> None:
    player_state = session_state["player_state"]
    if container_name == "scene_pool":
        _set_scene_pool(session_state, entries)
    elif container_name == "inventory":
        player_state["inventory"] = entries
    else:
        player_state["equipped_items"] = entries
        player_state["held_items"] = deepcopy(entries)


def _build_target_entry(
    source_entry: dict[str, Any],
    entity_id: str,
    entity_type: str,
    target_name: str,
    quantity: int,
    session_state: GameSessionState,
) -> dict[str, Any]:
    name = str(source_entry.get("name", source_entry.get("canonical_name", entity_id))).strip() or entity_id
    aliases = list(source_entry.get("aliases", [])) if isinstance(source_entry.get("aliases", []), list) else []
    if target_name == "scene_pool":
        location_id = _location_id(session_state)
        return {
            "entity_id": entity_id,
            "name": name,
            "normalized_name": normalize_scene_memory_name(name),
            "entity_type": entity_type if entity_type in {"scene_entity", "interactable", "actor"} else "scene_entity",
            "status": "available",
            "truth_status": "soft_scene",
            "scene_id": location_id,
            "location_id": location_id,
            "aliases": aliases or [name],
            "source": "transferred",
            "first_seen_turn": session_state.get("turn_count", 0) + 1,
            "last_seen_turn": session_state.get("turn_count", 0) + 1,
            "mention_count": 1,
            "quantity": quantity,
            "raw": {
                "source": "transfer",
                "origin_entity_id": entity_id,
                "origin_entity_type": entity_type,
            },
        }
    return {
        "item_id": entity_id,
        "name": name,
        "quantity": quantity,
        "aliases": aliases,
    }


def _remove_duplicate_presence(
    session_state: GameSessionState,
    entity_id: str,
    target_name: str,
) -> None:
    """Keep canonical entity ids from appearing in multiple transfer containers."""

    for container_name in {"scene_pool", "inventory", "equipped"} - {target_name}:
        _remove_from_container(session_state, container_name, entity_id, 10**9)


def _sync_equipped_views(session_state: GameSessionState) -> None:
    equipped_items = session_state["player_state"].setdefault("equipped_items", [])
    session_state["player_state"]["held_items"] = deepcopy(equipped_items)


def _is_actor_like(entity_type: str, entry: dict[str, Any]) -> bool:
    subtype = str(entry.get("subtype", entry.get("raw", {}).get("subtype", ""))).casefold()
    raw_type = str(entry.get("entity_type", entry.get("raw", {}).get("entity_type", ""))).casefold()
    return entity_type == "actor" or raw_type == "actor" or subtype == "npc"


def _get_scene_pool(session_state: GameSessionState) -> list[dict[str, Any]]:
    scene_pool = session_state.get("scene_pool", session_state.get("scene_entity_pool", []))
    if not isinstance(scene_pool, list):
        scene_pool = []
    _set_scene_pool(session_state, scene_pool)
    return scene_pool


def _set_scene_pool(session_state: GameSessionState, scene_pool: list[dict[str, Any]]) -> None:
    session_state["scene_pool"] = scene_pool
    session_state["scene_entity_pool"] = scene_pool


def _location_id(session_state: GameSessionState) -> str:
    location = session_state.get("player_state", {}).get("current_location", {})
    region_id = str(location.get("region_id", "unknown")).strip() or "unknown"
    detail = str(location.get("detail", "")).strip()
    return f"{region_id}:{detail}" if detail else region_id


def _summary_label(source_name: str, target_name: str) -> str:
    if target_name == "inventory":
        return "Picked up" if source_name == "scene_pool" else "Unequipped"
    if target_name == "equipped":
        return "Equipped"
    return "Dropped"


def _build_change_summary(applied_changes: list[dict[str, Any]]) -> list[dict[str, str]]:
    summary: list[dict[str, str]] = []
    for change in applied_changes:
        label = str(change.get("summary_label", "Changed")).strip() or "Changed"
        display_name = str(change.get("display_name", change.get("entity_name", ""))).strip()
        if not display_name:
            continue
        text = _change_summary_text(change, label, display_name)
        kind = "positive" if label in {"Picked up", "Equipped"} else "neutral"
        if change.get("type") in {"skill_change", "stat_change", "currency_change", "status_effect_change"}:
            kind = "negative" if label in {"Skill reduced", "Stat decreased", "Spent", "Removed"} else "positive"
        summary.append({"kind": kind, "text": text})
    return summary


def _change_summary_text(change: dict[str, Any], label: str, display_name: str) -> str:
    change_type = change.get("type")
    old_value = change.get("old_value")
    new_value = change.get("new_value")
    amount = change.get("amount")
    if change_type == "skill_change":
        if label in {"Skill improved", "Skill reduced"}:
            return f"{label}: {display_name} {old_value} -> {new_value}"
        if label == "Skill learned":
            return f"Skill learned: {display_name}"
        return f"{label}: {display_name}"
    if change_type == "stat_change":
        if label == "Stat increased":
            return f"Stat increased: {display_name} +{amount}"
        if label == "Stat decreased":
            return f"Stat decreased: {display_name} -{amount}"
        return f"{label}: {display_name} {old_value} -> {new_value}"
    if change_type == "currency_change":
        if label in {"Gained", "Spent"}:
            return f"{label}: {amount} {display_name}"
        return f"{label}: {display_name} {old_value} -> {new_value}"
    if change_type == "status_effect_change":
        return f"{label}: {display_name}"
    return f"{label}: {display_name}"


def _container_summary(session_state: GameSessionState) -> dict[str, list[str]]:
    return {
        "inventory": [
            str(item.get("item_id", item.get("entity_id", "")))
            for item in session_state["player_state"].get("inventory", [])
        ],
        "equipped": [
            str(item.get("item_id", item.get("entity_id", "")))
            for item in session_state["player_state"].get("equipped_items", [])
        ],
        "scene_pool": [
            str(item.get("entity_id", item.get("item_id", "")))
            for item in _get_scene_pool(session_state)
        ],
    }


def _apply_state_mutations(
    session_state: GameSessionState,
    action_result: ActionProcessingContract,
) -> dict[str, Any]:
    """Validate and apply non-transfer Judge state intents."""

    received_intents = _mutation_intents(action_result)
    debug: dict[str, Any] = {
        "received_intents": received_intents,
        "applied_changes": [],
        "skipped_changes": [],
        "validation": [],
        "state_summary": {},
    }
    handlers = [
        ("skill_changes", _apply_skill_change),
        ("stat_changes", _apply_stat_change),
        ("currency_changes", _apply_currency_change),
        ("status_effect_changes", _apply_status_effect_change),
    ]
    for intent_key, handler in handlers:
        for intent in received_intents[intent_key]:
            outcome = handler(session_state, intent)
            debug["validation"].append({**outcome, "intent_type": intent_key})
            if outcome["applied"]:
                debug["applied_changes"].append(outcome["change"])
            else:
                debug["skipped_changes"].append(
                    {
                        "intent_type": intent_key,
                        "intent": intent,
                        "reason": outcome["reason"],
                    }
                )
    debug["state_summary"] = _player_state_summary(session_state)
    return debug


def _mutation_intents(action_result: ActionProcessingContract) -> dict[str, list[dict[str, Any]]]:
    state_intents = action_result.get("state_intents", {})
    return {
        "skill_changes": list(state_intents.get("skill_changes", [])),
        "stat_changes": list(state_intents.get("stat_changes", [])),
        "currency_changes": list(state_intents.get("currency_changes", [])),
        "status_effect_changes": list(state_intents.get("status_effect_changes", [])),
    }


def _apply_skill_change(session_state: GameSessionState, intent: dict[str, Any]) -> dict[str, Any]:
    skills = session_state["player_state"].setdefault("skills", [])
    op = str(intent.get("op", "")).strip()
    skill_id = str(intent.get("skill_id", "")).strip()
    skill = _find_by_id(skills, "skill_id", skill_id)
    if not skill_id:
        return _skipped_mutation(intent, "Missing skill_id.")
    if op == "add":
        if skill is not None:
            return _skipped_mutation(intent, "Skill already exists.")
        skill_data = intent.get("skill_data", {}) if isinstance(intent.get("skill_data", {}), dict) else {}
        if not skill_data.get("skill_id") or not skill_data.get("name"):
            return _skipped_mutation(intent, "Adding a new skill requires full skill_data with skill_id and name.")
        new_skill = deepcopy(skill_data)
        new_skill["skill_id"] = skill_id
        new_skill["level"] = _safe_number(new_skill.get("level", intent.get("new_value", intent.get("amount", 1))), 1)
        skills.append(new_skill)
        return _applied_mutation(intent, "skill_change", op, skill_id, new_skill["name"], None, new_skill["level"], new_skill["level"], "Skill learned")
    if skill is None:
        return _skipped_mutation(intent, "Skill does not exist.")
    name = str(skill.get("name", skill_id))
    old_value = _safe_number(skill.get("level", 0), 0)
    if op == "remove":
        skills.remove(skill)
        return _applied_mutation(intent, "skill_change", op, skill_id, name, old_value, None, None, "Skill removed")
    if op == "level_up":
        new_value = old_value + _safe_number(intent.get("amount", 1), 1)
    elif op == "level_down":
        new_value = old_value - _safe_number(intent.get("amount", 1), 1)
    elif op == "set_level":
        new_value = _safe_number(intent.get("new_value"), old_value)
    else:
        return _skipped_mutation(intent, "Unsupported skill operation.")
    if new_value < 0:
        return _skipped_mutation(intent, "Skill level cannot go below 0.")
    skill["level"] = new_value
    label = "Skill improved" if new_value >= old_value else "Skill reduced"
    return _applied_mutation(intent, "skill_change", op, skill_id, name, old_value, new_value, intent.get("amount"), label)


def _apply_stat_change(session_state: GameSessionState, intent: dict[str, Any]) -> dict[str, Any]:
    stats = session_state["player_state"].setdefault("stats", [])
    op = str(intent.get("op", "")).strip()
    stat_id = str(intent.get("stat_id", "")).strip()
    stat = _find_by_id(stats, "stat_id", stat_id)
    if not stat_id:
        return _skipped_mutation(intent, "Missing stat_id.")
    if stat is None:
        return _skipped_mutation(intent, "Stat does not exist.")
    name = str(stat.get("name", stat_id))
    old_value = _safe_number(stat.get("value", 0), 0)
    if op == "increase":
        new_value = old_value + _safe_number(intent.get("amount", 1), 1)
        label = "Stat increased"
    elif op == "decrease":
        new_value = old_value - _safe_number(intent.get("amount", 1), 1)
        label = "Stat decreased"
    elif op == "set":
        new_value = _safe_number(intent.get("new_value"), old_value)
        label = "Stat set"
    else:
        return _skipped_mutation(intent, "Unsupported stat operation.")
    stat["value"] = new_value
    return _applied_mutation(intent, "stat_change", op, stat_id, name, old_value, new_value, intent.get("amount"), label)


def _apply_currency_change(session_state: GameSessionState, intent: dict[str, Any]) -> dict[str, Any]:
    currencies = session_state["player_state"].setdefault("currencies", [])
    op = str(intent.get("op", "")).strip()
    currency_id = str(intent.get("currency_id", "")).strip()
    currency = _find_by_id(currencies, "currency_id", currency_id)
    if not currency_id:
        return _skipped_mutation(intent, "Missing currency_id.")
    if currency is None:
        currency_data = intent.get("currency_data", {}) if isinstance(intent.get("currency_data", {}), dict) else {}
        if op != "add" or not currency_data.get("currency_id") or not currency_data.get("name"):
            return _skipped_mutation(intent, "Currency does not exist.")
        currency = deepcopy(currency_data)
        currency["currency_id"] = currency_id
        currency["amount"] = 0
        currencies.append(currency)
    name = str(currency.get("name", currency_id))
    old_value = _safe_number(currency.get("amount", 0), 0)
    amount = _safe_number(intent.get("amount", 1), 1)
    if op == "add":
        new_value = old_value + amount
        label = "Gained"
    elif op == "spend":
        if old_value - amount < 0:
            return _skipped_mutation(intent, "Currency cannot go below 0.")
        new_value = old_value - amount
        label = "Spent"
    elif op == "set":
        new_value = amount
        if new_value < 0:
            return _skipped_mutation(intent, "Currency cannot go below 0.")
        label = "Currency set"
    else:
        return _skipped_mutation(intent, "Unsupported currency operation.")
    currency["amount"] = new_value
    return _applied_mutation(intent, "currency_change", op, currency_id, name, old_value, new_value, amount, label)


def _apply_status_effect_change(session_state: GameSessionState, intent: dict[str, Any]) -> dict[str, Any]:
    status_effects = session_state["player_state"].setdefault("status_effects", [])
    op = str(intent.get("op", "")).strip()
    effect_id = str(intent.get("effect_id", "")).strip()
    effect = _find_by_id(status_effects, "effect_id", effect_id)
    if not effect_id:
        return _skipped_mutation(intent, "Missing effect_id.")
    if op == "remove":
        if effect is None:
            return _skipped_mutation(intent, "Status effect does not exist.")
        status_effects.remove(effect)
        return _applied_mutation(intent, "status_effect_change", op, effect_id, str(effect.get("name", effect_id)), effect.get("remaining_duration"), None, None, "Removed")
    if op not in {"add", "refresh"}:
        return _skipped_mutation(intent, "Unsupported status effect operation.")
    effect_data = intent.get("effect_data", {}) if isinstance(intent.get("effect_data", {}), dict) else {}
    if effect is None:
        if not effect_data.get("effect_id") or not effect_data.get("name"):
            return _skipped_mutation(intent, "Adding a status effect requires effect_data with effect_id and name.")
        effect = deepcopy(effect_data)
        effect["effect_id"] = effect_id
        status_effects.append(effect)
        label = "Gained"
        old_value = None
    else:
        effect.update(deepcopy(effect_data))
        effect["effect_id"] = effect_id
        label = "Refreshed"
        old_value = effect.get("remaining_duration")
    if intent.get("duration") is not None:
        effect["remaining_duration"] = intent["duration"]
    name = str(effect.get("name", effect_id))
    return _applied_mutation(intent, "status_effect_change", op, effect_id, name, old_value, effect.get("remaining_duration"), None, label)


def _find_by_id(entries: list[dict[str, Any]], id_key: str, entity_id: str) -> dict[str, Any] | None:
    return next((entry for entry in entries if str(entry.get(id_key, "")) == entity_id), None)


def _safe_number(value: object, fallback: int | float) -> int | float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return int(number) if number.is_integer() else number


def _skipped_mutation(intent: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "applied": False,
        "reason": reason,
        "intent": intent,
        "change": None,
    }


def _applied_mutation(
    intent: dict[str, Any],
    change_type: str,
    op: str,
    entity_id: str,
    entity_name: str,
    old_value: Any,
    new_value: Any,
    amount: Any,
    summary_label: str,
) -> dict[str, Any]:
    return {
        "applied": True,
        "reason": "",
        "intent": intent,
        "change": {
            "type": change_type,
            "op": op,
            "entity_id": entity_id,
            "entity_name": entity_name,
            "old_value": old_value,
            "new_value": new_value,
            "amount": amount,
            "summary_label": summary_label,
            "display_name": entity_name,
        },
    }


def _player_state_summary(session_state: GameSessionState) -> dict[str, Any]:
    player_state = session_state["player_state"]
    return {
        "skills": {skill.get("skill_id"): skill.get("level") for skill in player_state.get("skills", [])},
        "stats": {stat.get("stat_id"): stat.get("value") for stat in player_state.get("stats", [])},
        "currencies": {currency.get("currency_id"): currency.get("amount") for currency in player_state.get("currencies", [])},
        "status_effects": [effect.get("effect_id") for effect in player_state.get("status_effects", [])],
    }


def _resolve_quality_side_effects(
    session_state: GameSessionState,
    action_result: ActionProcessingContract,
) -> None:
    """Resolve conditional Judge side effects with deterministic code-driven randomness."""

    proposed_side_effects = list(action_result.get("proposed_side_effects", action_result["side_effects"]))
    normalized_quality = clamp_outcome_quality(action_result.get("outcome_quality", 50))
    chance = quality_side_effect_chance(normalized_quality)
    seed = (
        f"{session_state['session_id']}|{session_state['turn_count'] + 1}|"
        f"{action_result['raw_player_input']}|{action_result['expanded_player_intent']}"
    )
    applied = bool(proposed_side_effects) and should_apply_quality_side_effect(
        normalized_quality,
        rng=Random(seed),
    )
    action_result["outcome_quality"] = normalized_quality
    action_result["proposed_side_effects"] = proposed_side_effects
    action_result["quality_side_effect_chance"] = chance
    action_result["quality_side_effect_applied"] = applied
    action_result["applied_side_effects"] = proposed_side_effects if applied else []
    action_result["side_effects"] = list(action_result["applied_side_effects"])

    logger.info(
        "Quality side effects: quality=%s chance=%.3f applied=%s proposed=%s",
        normalized_quality,
        chance,
        applied,
        proposed_side_effects,
    )


def _build_outcome_summary(
    action_result: ActionProcessingContract,
    action_category: str,
) -> str:
    """Build a concise consequence summary from Judge output."""

    summary = action_result["attempt_summary"].strip() or "Unable to evaluate action."
    if action_result["action_result"] == "blocked" and action_result["blockers"]:
        summary = f"{summary} Blocked by: {action_result['blockers'][0]}."
    elif action_result["what_succeeds"]:
        summary = f"{summary} Success focus: {action_result['what_succeeds'][0]}."
    elif action_result["what_fails"]:
        summary = f"{summary} Failure focus: {action_result['what_fails'][0]}."

    if action_result["applied_side_effects"]:
        summary = f"{summary} Side effect: {action_result['applied_side_effects'][0]}."
    if action_result["revealed_information"]:
        summary = f"{summary} Discovery: {action_result['revealed_information'][0]}."
    if action_category == "combat_attempt":
        summary = f"{summary} Exploration mode prevents combat resolution."
    return summary
