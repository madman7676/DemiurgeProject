"""Contracts for non-player character state."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


RelevanceLevel = Literal["background", "supporting", "major"]


class NPCIdentity(TypedDict):
    """Stable identity fields for an NPC."""

    npc_id: str
    name: str
    aliases: NotRequired[list[str]]


class NPCLocation(TypedDict):
    """Minimal location reference for NPC placement."""

    region_id: str
    area_id: NotRequired[str]
    detail: NotRequired[str]


class NPCCharacterProfile(TypedDict):
    """Personality and presentation summary for an NPC."""

    archetype: str
    personality_traits: list[str]
    summary: str


class NPCRelationshipToPlayer(TypedDict):
    """Current relationship state between an NPC and the player."""

    status: str
    trust: NotRequired[int | float]
    affinity: NotRequired[int | float]
    tension: NotRequired[int | float]
    notes: NotRequired[str]


class NPCConnection(TypedDict):
    """Link from one NPC to another relevant NPC."""

    npc_id: str
    connection_type: str
    strength: NotRequired[int | float]
    notes: NotRequired[str]


class FutureCombatFields(TypedDict):
    """Optional placeholder for future combat-related NPC data."""

    threat_level: NotRequired[int | float]
    combat_role: NotRequired[str]
    preferred_style: NotRequired[str]


class NPCStateContract(TypedDict):
    """Top-level NPC state contract used by routing and narrative systems."""

    identity: NPCIdentity
    role: str
    location: NPCLocation
    relevance_level: RelevanceLevel
    character: NPCCharacterProfile
    global_goal: str
    current_goal: str
    ambition_level: int | float
    reaction_threshold: int | float
    relationship_to_player: NPCRelationshipToPlayer
    connections: list[NPCConnection]
    combat: NotRequired[FutureCombatFields]
