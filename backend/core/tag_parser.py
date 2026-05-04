"""Simple parser for Narrator [[...]] tags."""

from __future__ import annotations

import re
from typing import Any


ALLOWED_ENTITY_CLASSES = {"item", "npc", "enemy", "place", "skill", "currency"}
ALLOWED_VISIBILITY = {"available", "background"}
TAG_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


def parse_tags(text: str) -> dict[str, list[dict[str, Any]]]:
    """Extract known tags and collect malformed/skipped tags."""

    parsed: dict[str, list[dict[str, Any]]] = {
        "entities": [],
        "player_changes": [],
        "malformed_or_skipped_tags": [],
    }

    for match in TAG_PATTERN.finditer(text or ""):
        raw = match.group(1).strip()
        parts = [part.strip() for part in raw.split("|")]
        if not parts or not parts[0]:
            _skip(parsed, raw, "empty_tag")
            continue

        kind = parts[0]
        if kind.startswith("entity:"):
            entity_class = kind.split(":", 1)[1].strip()
            if len(parts) < 4:
                _skip(parsed, raw, "malformed_entity")
                continue
            if entity_class not in ALLOWED_ENTITY_CLASSES:
                _skip(parsed, raw, "unknown_entity_class")
                continue
            visibility = parts[3] or "available"
            if visibility not in ALLOWED_VISIBILITY:
                _skip(parsed, raw, "unknown_visibility")
                continue
            entity_id = parts[1]
            name = parts[2]
            if not entity_id or not name:
                _skip(parsed, raw, "missing_entity_id_or_name")
                continue
            parsed["entities"].append(
                {
                    "raw": raw,
                    "id": entity_id,
                    "class": entity_class,
                    "name": name,
                    "visibility": visibility,
                    "icon": parts[4] if len(parts) > 4 and parts[4] else "",
                    "span": [match.start(), match.end()],
                }
            )
            continue

        if kind == "player_change":
            if len(parts) != 2 or not parts[1]:
                _skip(parsed, raw, "malformed_player_change")
                continue
            command_parts = [part.strip() for part in parts[1].split(":")]
            command = command_parts[0] if command_parts else ""
            if command not in {
                "add_item",
                "remove_item",
                "add_currency",
                "remove_currency",
                "add_skill",
                "remove_skill",
                "set_location",
            }:
                _skip(parsed, raw, "unknown_player_change")
                continue
            parsed["player_changes"].append(
                {
                    "raw": raw,
                    "command": command,
                    "args": command_parts[1:],
                    "span": [match.start(), match.end()],
                }
            )
            continue

        _skip(parsed, raw, "unknown_tag")

    return parsed


def strip_tags(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", TAG_PATTERN.sub("", text or "")).strip()
    return re.sub(r"\s+([.,!?;:])", r"\1", cleaned)


def strip_player_change_tags(text: str) -> str:
    """Remove backend mutation tags while preserving entity tags for UI rendering."""

    def replace_tag(match: re.Match[str]) -> str:
        raw = match.group(1).strip()
        return "" if raw.startswith("player_change|") else match.group(0)

    cleaned = re.sub(r"\s+", " ", TAG_PATTERN.sub(replace_tag, text or "")).strip()
    return re.sub(r"\s+([.,!?;:])", r"\1", cleaned)


def _skip(parsed: dict[str, list[dict[str, Any]]], raw: str, reason: str) -> None:
    parsed["malformed_or_skipped_tags"].append({"raw": raw, "reason": reason})
