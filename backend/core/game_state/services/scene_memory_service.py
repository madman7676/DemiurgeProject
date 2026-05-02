"""Scene memory updates from narrator-produced entity markers."""

from __future__ import annotations

import logging
from typing import Any

from backend.modules.entity_resolver.schemas.entity_resolver_contracts import (
    EntityResolutionResult,
)
from backend.modules.narrator.services.narrator_service import normalize_scene_memory_name


logger = logging.getLogger(__name__)
SCENE_STALE_TURN_THRESHOLD = 3


def apply_narrator_scene_memory(
    session_state: dict[str, Any],
    narrator_output: str,
    parsed_mentions: dict[str, list[dict[str, Any]]],
    entity_resolution: EntityResolutionResult,
    current_turn: int,
    stale_turn_threshold: int = SCENE_STALE_TURN_THRESHOLD,
) -> dict[str, Any]:
    """Validate and store narrator marker mentions into scene/reference memory."""

    location_id = _location_id(session_state)
    cleanup_debug = cleanup_scene_pool(
        session_state=session_state,
        current_turn=current_turn,
        location_id=location_id,
        stale_turn_threshold=stale_turn_threshold,
    )
    unresolved_names = _blocked_reference_names(entity_resolution)
    debug = {
        "raw_narrator_output": narrator_output,
        "parsed_mentions": parsed_mentions,
        "scene_entity_mentions": parsed_mentions.get("scene_entity_mentions", []),
        "reference_mentions": parsed_mentions.get("reference_mentions", []),
        "player_entity_mentions": parsed_mentions.get("player_entity_mentions", []),
        "scene_pool_updates": [],
        "reference_pool_updates": [],
        "cleanup_removals": cleanup_debug["removed"],
        "validation_warnings": [],
    }

    for mention in parsed_mentions.get("scene_entity_mentions", []):
        if mention["normalized_name"] in unresolved_names:
            warning = f"Ignored narrator scene entity '{mention['name']}' because it conflicts with unresolved or ambiguous turn references."
            debug["validation_warnings"].append(warning)
            logger.warning(warning)
            continue
        update = _upsert_scene_entity(
            session_state=session_state,
            mention=mention,
            current_turn=current_turn,
            location_id=location_id,
        )
        debug["scene_pool_updates"].append(update)

    for mention in parsed_mentions.get("reference_mentions", []):
        update = _upsert_reference(
            session_state=session_state,
            mention=mention,
            current_turn=current_turn,
        )
        debug["reference_pool_updates"].append(update)

    for mention in parsed_mentions.get("player_entity_mentions", []):
        if _is_valid_player_entity(session_state, entity_resolution, mention["normalized_name"]):
            debug["validation_warnings"].append(
                f"Validated player_entity marker '{mention['name']}' for debug annotation only."
            )
        else:
            warning = f"Ignored invalid player_entity marker '{mention['name']}'."
            debug["validation_warnings"].append(warning)
            logger.warning(warning)

    logger.info(
        "Scene memory update: scene_updates=%s reference_updates=%s warnings=%s cleanup=%s",
        debug["scene_pool_updates"],
        debug["reference_pool_updates"],
        debug["validation_warnings"],
        debug["cleanup_removals"],
    )
    return debug


def cleanup_scene_pool(
    session_state: dict[str, Any],
    current_turn: int,
    location_id: str,
    stale_turn_threshold: int = SCENE_STALE_TURN_THRESHOLD,
) -> dict[str, Any]:
    """Clear or prune soft scene memory according to location and turn age."""

    anchor = session_state.setdefault(
        "scene_pool_anchor",
        {"region_id": location_id, "detail": "", "turn": current_turn},
    )
    previous_location_id = _anchor_location_id(anchor)
    removed = []

    if previous_location_id != location_id:
        removed = list(_get_scene_pool(session_state))
        _set_scene_pool(session_state, [])
        _update_anchor(session_state, current_turn)
        return {"removed": removed, "reason": "location_changed"}

    kept = []
    for entry in _get_scene_pool(session_state):
        last_seen_turn = int(entry.get("last_seen_turn", current_turn))
        if current_turn - last_seen_turn > stale_turn_threshold:
            removed.append(entry)
        else:
            kept.append(entry)
    _set_scene_pool(session_state, kept)
    _update_anchor(session_state, current_turn)
    return {"removed": removed, "reason": "stale_turns"}


def _upsert_scene_entity(
    session_state: dict[str, Any],
    mention: dict[str, Any],
    current_turn: int,
    location_id: str,
) -> dict[str, Any]:
    scene_pool = _get_scene_pool(session_state)
    normalized_name = mention["normalized_name"]
    status = "available" if mention.get("status") == "available" else "background"
    existing = next(
        (
            entry
            for entry in scene_pool
            if entry.get("normalized_name") == normalized_name
            and entry.get("location_id", location_id) == location_id
        ),
        None,
    )
    if existing is not None:
        existing["mention_count"] = int(existing.get("mention_count", 0)) + 1
        existing["last_seen_turn"] = current_turn
        if status == "available":
            existing["status"] = "available"
        return {"action": "updated", "entity_id": existing["entity_id"], "status": existing.get("status")}

    entity_id = f"scene:{_slugify(location_id)}:{_slugify(normalized_name)}"
    entry = {
        "entity_id": entity_id,
        "name": mention["name"],
        "normalized_name": normalized_name,
        "entity_type": "scene_entity",
        "status": status,
        "truth_status": "soft_scene",
        "scene_id": location_id,
        "location_id": location_id,
        "aliases": [mention["name"]],
        "source": "scene_pool",
        "first_seen_turn": current_turn,
        "last_seen_turn": current_turn,
        "mention_count": 1,
        "raw": {"source": "narrator", "status": status},
    }
    scene_pool.append(entry)
    _set_scene_pool(session_state, scene_pool)
    return {"action": "created", "entity_id": entity_id, "status": status}


def _upsert_reference(
    session_state: dict[str, Any],
    mention: dict[str, Any],
    current_turn: int,
) -> dict[str, Any]:
    reference_pool = session_state.setdefault("reference_pool", [])
    normalized_name = mention["normalized_name"]
    existing = next((entry for entry in reference_pool if entry["normalized_name"] == normalized_name), None)
    if existing is not None:
        existing["mention_count"] += 1
        existing["last_seen_turn"] = current_turn
        return {"action": "updated", "reference_id": existing["reference_id"]}

    reference_id = f"reference:{_slugify(normalized_name)}"
    reference_pool.append(
        {
            "reference_id": reference_id,
            "name": mention["name"],
            "normalized_name": normalized_name,
            "status": "known_reference",
            "availability": "not_present",
            "first_seen_turn": current_turn,
            "last_seen_turn": current_turn,
            "mention_count": 1,
        }
    )
    return {"action": "created", "reference_id": reference_id}


def _is_valid_player_entity(
    session_state: dict[str, Any],
    entity_resolution: EntityResolutionResult,
    normalized_name: str,
) -> bool:
    player_state = session_state.get("player_state", {})
    player_entities = (
        player_state.get("inventory", [])
        + player_state.get("held_items", [])
        + player_state.get("equipped_items", [])
        + player_state.get("skills", [])
    )
    for entry in player_entities:
        names = [entry.get("name", ""), *entry.get("aliases", [])]
        if normalized_name in {normalize_scene_memory_name(str(name)) for name in names if name}:
            return True
    for entity in entity_resolution.get("resolved_entities", []):
        names = [entity.get("source_text", ""), entity.get("canonical_name", "")]
        if normalized_name in {normalize_scene_memory_name(str(name)) for name in names if name}:
            return True
    return False


def _blocked_reference_names(entity_resolution: EntityResolutionResult) -> set[str]:
    names = set()
    for mention in entity_resolution.get("unresolved_mentions", []):
        names.add(normalize_scene_memory_name(mention.get("source_text", "")))
    for mention in entity_resolution.get("ambiguous_mentions", []):
        names.add(normalize_scene_memory_name(mention.get("source_text", "")))
    return {name for name in names if name}


def _get_scene_pool(session_state: dict[str, Any]) -> list[dict[str, Any]]:
    scene_pool = session_state.get("scene_pool")
    legacy_pool = session_state.get("scene_entity_pool", [])
    if not isinstance(scene_pool, list) or (not scene_pool and isinstance(legacy_pool, list) and legacy_pool):
        scene_pool = legacy_pool
    if not isinstance(scene_pool, list):
        scene_pool = []
    _set_scene_pool(session_state, scene_pool)
    return scene_pool


def _set_scene_pool(session_state: dict[str, Any], scene_pool: list[dict[str, Any]]) -> None:
    session_state["scene_pool"] = scene_pool
    session_state["scene_entity_pool"] = scene_pool


def _location_id(session_state: dict[str, Any]) -> str:
    location = session_state.get("player_state", {}).get("current_location", {})
    region_id = str(location.get("region_id", "unknown")).strip() or "unknown"
    detail = str(location.get("detail", "")).strip()
    return f"{region_id}:{detail}" if detail else region_id


def _anchor_location_id(anchor: dict[str, Any]) -> str:
    region_id = str(anchor.get("region_id", "unknown")).strip() or "unknown"
    detail = str(anchor.get("detail", "")).strip()
    return f"{region_id}:{detail}" if detail else region_id


def _update_anchor(session_state: dict[str, Any], current_turn: int) -> None:
    location = session_state.get("player_state", {}).get("current_location", {})
    session_state["scene_pool_anchor"] = {
        "region_id": str(location.get("region_id", "unknown")).strip() or "unknown",
        "detail": str(location.get("detail", "")).strip(),
        "turn": current_turn,
    }


def _slugify(value: str) -> str:
    return normalize_scene_memory_name(value).replace(" ", "_") or "entity"
