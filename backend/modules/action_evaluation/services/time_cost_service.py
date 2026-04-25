"""Time-cost estimation for exploration actions."""

from __future__ import annotations

import re

from backend.modules.action_evaluation.schemas.action_evaluation_contracts import (
    ActionProcessingContract,
    TimeCost,
)

DURATION_MINUTES = {
    "instant": 1,
    "short": 5,
    "medium": 12,
    "long": 30,
    "extended": 90,
}
EFFORT_BONUS = {"low": 0, "medium": 3, "high": 8}


def estimate_time_cost(judge_output: ActionProcessingContract) -> TimeCost:
    """Estimate time cost from Judge v1.1 time hints and resolved outcome."""

    raw_player_input = judge_output["expanded_player_intent"]
    lowered = raw_player_input.lower()
    time_hints = judge_output["time_hints"]
    minutes = DURATION_MINUTES.get(time_hints["duration_class"], 5)
    minutes += EFFORT_BONUS.get(time_hints["effort_level"], 3)

    if any(keyword in lowered for keyword in ["carefully", "thoroughly", "search", "investigate"]):
        minutes += 3
    if any(keyword in lowered for keyword in ["quickly", "briefly"]):
        minutes = max(1, minutes - 2)
    if judge_output["action_type"] == "idle":
        explicit_wait = _parse_explicit_wait_minutes(lowered)
        if explicit_wait is not None:
            minutes = explicit_wait
    if time_hints["interrupted"]:
        minutes = max(1, minutes - 2)
    if judge_output["action_result"] == "blocked":
        minutes = min(minutes, 2)
    elif judge_output["action_result"] == "failure" and judge_output["outcome_quality"] >= 75:
        minutes += 4
    elif judge_output["action_result"] == "success" and judge_output["outcome_quality"] >= 80:
        minutes = max(1, minutes - 1)

    if judge_output["interpreted_intent"].get("primary_goal") == "attempt_combat":
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
