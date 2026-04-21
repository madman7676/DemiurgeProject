"""Compatibility layer for world rule schemas.

The canonical contracts live in ``backend.core.world_rules.contracts``.
Keep this module as the main import surface for JSON-oriented world definitions.
"""

from backend.core.world_rules.contracts import (
    ActiveFeatureReference,
    DiscoveredRuleCandidate,
    EvolutionSettings,
    HardRule,
    MetaRule,
    RegionDefinition,
    SoftRule,
    TimeModel,
    WorldIdentity,
    WorldRulesDocument,
)

__all__ = [
    "ActiveFeatureReference",
    "DiscoveredRuleCandidate",
    "EvolutionSettings",
    "HardRule",
    "MetaRule",
    "RegionDefinition",
    "SoftRule",
    "TimeModel",
    "WorldIdentity",
    "WorldRulesDocument",
]
