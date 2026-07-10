"""Parser for Hyperlite Narrator [[player_change|...]] tags."""

from __future__ import annotations

import re
from typing import Any


TAG_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")
PLAYER_CHANGE_ARG_COUNTS = {
    "add_item": 4,
    "remove_item": 2,
    "add_resource": 4,
    "remove_resource": 2,
    "add_skill": 3,
    "remove_skill": 1,
}


def parse_tags(text: str) -> dict[str, list[dict[str, Any]]]:
    """Extract valid player changes and collect all invalid service tags."""

    parsed: dict[str, list[dict[str, Any]]] = {
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
        if kind == "player_change":
            if len(parts) < 2:
                _skip(parsed, raw, "malformed_player_change")
                continue
            command = parts[1]
            expected_arg_count = PLAYER_CHANGE_ARG_COUNTS.get(command)
            if expected_arg_count is None:
                _skip(parsed, raw, "unknown_player_change")
                continue
            args = parts[2:]
            if len(args) != expected_arg_count or any(arg == "" for arg in args):
                _skip(parsed, raw, "malformed_player_change")
                continue
            parsed["player_changes"].append(
                {
                    "raw": raw,
                    "command": command,
                    "args": args,
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
    """Remove valid Hyperlite mutation tags from text shown in the UI."""

    def replace_tag(match: re.Match[str]) -> str:
        raw = match.group(1).strip()
        if raw.startswith("player_change|"):
            return ""
        return match.group(0)

    cleaned = re.sub(r"\s+", " ", TAG_PATTERN.sub(replace_tag, text or "")).strip()
    return re.sub(r"\s+([.,!?;:])", r"\1", cleaned)


def _skip(parsed: dict[str, list[dict[str, Any]]], raw: str, reason: str) -> None:
    parsed["malformed_or_skipped_tags"].append({"raw": raw, "reason": reason})
