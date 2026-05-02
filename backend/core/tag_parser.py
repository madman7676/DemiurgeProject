"""Simple tag extraction for Narrator output."""

from __future__ import annotations

import re
from typing import Any


TAG_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


def parse_tags(text: str) -> dict[str, list[dict[str, Any]]]:
    """Extract supported tags without validating whether they make sense."""

    parsed: dict[str, list[dict[str, Any]]] = {
        "all": [],
        "entities": [],
        "player_changes": [],
    }
    for match in TAG_PATTERN.finditer(text or ""):
        raw = match.group(1).strip()
        parts = [part.strip() for part in raw.split("|")]
        if not parts or not parts[0]:
            continue

        tag = {"raw": raw, "kind": parts[0], "parts": parts, "span": [match.start(), match.end()]}
        parsed["all"].append(tag)

        if parts[0].startswith("entity:"):
            entity = {
                **tag,
                "entity_type": parts[0].split(":", 1)[1].strip() or "unknown",
                "entity_id": parts[1] if len(parts) > 1 else "",
                "name": parts[2] if len(parts) > 2 else parts[1] if len(parts) > 1 else "",
                "status": parts[3] if len(parts) > 3 else "available",
            }
            parsed["entities"].append(entity)
        elif parts[0] == "player_change":
            parsed["player_changes"].append(
                {
                    **tag,
                    "change": parts[1] if len(parts) > 1 else "",
                }
            )

    return parsed
