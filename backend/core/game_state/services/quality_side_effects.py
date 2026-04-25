"""Deterministic helpers for Judge quality-based side-effect application."""

from __future__ import annotations

from random import Random


NEUTRAL_LOW = 41
NEUTRAL_HIGH = 60


def clamp_outcome_quality(outcome_quality: object) -> int:
    """Normalize Judge outcome quality into a safe integer range."""

    try:
        normalized = int(outcome_quality)
    except (TypeError, ValueError):
        return 50
    return max(0, min(100, normalized))


def quality_side_effect_chance(outcome_quality: object) -> float:
    """Return symmetric extra-effect chance based on distance from neutral quality."""

    normalized = clamp_outcome_quality(outcome_quality)
    if NEUTRAL_LOW <= normalized <= NEUTRAL_HIGH:
        return 0.0

    if normalized < NEUTRAL_LOW:
        distance = NEUTRAL_LOW - normalized
    else:
        distance = normalized - NEUTRAL_HIGH

    return min(distance, 40) / 40


def should_apply_quality_side_effect(
    outcome_quality: object,
    rng: Random | None = None,
) -> bool:
    """Gate conditional side effects without giving Judge responsibility for randomness."""

    chance = quality_side_effect_chance(outcome_quality)
    if chance <= 0:
        return False
    if chance >= 1:
        return True

    random_source = rng or Random(0)
    return random_source.random() < chance
