"""Time-cost estimation for exploration actions."""

from __future__ import annotations

import re

from backend.modules.action_evaluation.schemas.action_evaluation_contracts import (
    InterpretedIntent,
    TimeCost,
)


BASE_MINUTES = {
    "observe": 3,
    "talk": 5,
    "move": 8,
    "wait": 4,
    "interact": 6,
    "combat_attempt": 2,
}


def estimate_time_cost(
    action_category: str,
    raw_player_input: str,
    interpreted_intent: InterpretedIntent,
) -> TimeCost:
    """Estimate variable time cost without hardcoding a single fixed value."""

    lowered = raw_player_input.lower()
    word_count = len(raw_player_input.split())
    minutes = BASE_MINUTES.get(action_category, 4)
    minutes += min(max(word_count // 4, 0), 5)

    if any(keyword in lowered for keyword in ["carefully", "thoroughly", "search", "investigate"]):
        minutes += 3
    if any(keyword in lowered for keyword in ["quickly", "briefly"]):
        minutes = max(1, minutes - 2)
    if action_category == "wait":
        explicit_wait = _parse_explicit_wait_minutes(lowered)
        if explicit_wait is not None:
            minutes = explicit_wait

    if interpreted_intent.get("primary_goal") == "attempt_combat":
        minutes = max(minutes, 2)

    return {"amount": minutes, "unit": "minute"}


def _parse_explicit_wait_minutes(raw_player_input: str) -> int | None:
    """Parse very small explicit wait durations from plain language input."""

    hour_match = re.search(r"(\d+)\s*hour", raw_player_input)
    if hour_match:
        return max(1, int(hour_match.group(1)) * 60)

    minute_match = re.search(r"(\d+)\s*minute", raw_player_input)
    if minute_match:
        return max(1, int(minute_match.group(1)))

    return None

