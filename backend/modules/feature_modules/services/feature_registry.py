"""Registry placeholder for pluggable gameplay systems.

Future systems such as reputation, gacha, or combat can be attached here
without flattening the backend module structure.
"""

from __future__ import annotations


def build_available_modules(active_features: list[str]) -> list[str]:
    """Return the discrete module list that Router Agent may request from."""

    available_modules = ["npc_reaction"]
    available_modules.extend(
        f"feature_{feature_id}"
        for feature_id in active_features
        if feature_id
    )
    return sorted(set(available_modules))
