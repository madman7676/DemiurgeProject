"""Scene memory for the Lite tag-based pipeline."""

from __future__ import annotations

import re
from typing import Any


def apply_scene_memory(
    session_state: dict[str, Any],
    entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Upsert narrator-tagged entities into the current scene pool."""

    scene_pool = session_state.setdefault("scene_pool", [])
    turn = int(session_state.get("turn_count", 0))
    applied: list[dict[str, Any]] = []

    for entity in entities:
        entity_id = str(entity.get("entity_id") or "").strip()
        name = str(entity.get("name") or entity_id).strip()
        if not entity_id and not name:
            continue

        normalized_name = _normalize(name or entity_id)
        if not entity_id:
            entity_id = f"scene:{normalized_name.replace(' ', '_')}"

        existing = next(
            (
                entry
                for entry in scene_pool
                if entry.get("entity_id") == entity_id
                or entry.get("normalized_name") == normalized_name
            ),
            None,
        )
        if existing is None:
            scene_pool.append(
                {
                    "entity_id": entity_id,
                    "name": name or entity_id,
                    "normalized_name": normalized_name,
                    "entity_type": str(entity.get("entity_type") or "item"),
                    "kind": str(entity.get("entity_type") or "item"),
                    "status": str(entity.get("status") or "available"),
                    "source": "narrator_tag",
                    "first_seen_turn": turn,
                    "last_seen_turn": turn,
                    "mention_count": 1,
                    "raw": entity,
                }
            )
            applied.append({"action": "created", "entity_id": entity_id, "name": name})
            continue

        existing["name"] = name or existing.get("name", entity_id)
        existing["status"] = str(entity.get("status") or existing.get("status") or "available")
        existing["entity_type"] = str(entity.get("entity_type") or existing.get("entity_type") or "item")
        existing["kind"] = existing["entity_type"]
        existing["last_seen_turn"] = turn
        existing["mention_count"] = int(existing.get("mention_count", 0)) + 1
        existing["raw"] = entity
        applied.append({"action": "updated", "entity_id": entity_id, "name": name})

    return applied


def find_scene_entity(session_state: dict[str, Any], entity_id: str) -> dict[str, Any] | None:
    for entity in session_state.get("scene_pool", []):
        if entity.get("entity_id") == entity_id:
            return entity
    return None


def _normalize(value: str) -> str:
    lowered = value.casefold().strip()
    lowered = re.sub(r"[^\w\s-]", " ", lowered, flags=re.UNICODE)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered or "entity"
