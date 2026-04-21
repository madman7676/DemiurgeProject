"""Contracts for player-facing state data."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class PlayerIdentity(TypedDict):
    """Stable identity details for the player character."""

    player_id: str
    name: str
    aliases: NotRequired[list[str]]


class PlayerStat(TypedDict):
    """Single stat entry with room for future modifiers."""

    stat_id: str
    name: str
    value: int | float
    modifier: NotRequired[int | float]


class PlayerSkill(TypedDict):
    """Single skill entry tracked on the player profile."""

    skill_id: str
    name: str
    level: int | float
    tags: NotRequired[list[str]]


class InventoryItem(TypedDict):
    """Inventory item summary without item-system behavior."""

    item_id: str
    name: str
    quantity: int
    tags: NotRequired[list[str]]


class CurrencyBalance(TypedDict):
    """Named currency and the amount held by the player."""

    currency_id: str
    name: str
    amount: int | float


class StatusEffect(TypedDict):
    """Transient effect currently applied to the player."""

    effect_id: str
    name: str
    intensity: NotRequired[int | float]
    remaining_duration: NotRequired[int]
    duration_unit: NotRequired[str]


class LocationReference(TypedDict):
    """Minimal location link shared by player-facing state."""

    region_id: str
    area_id: NotRequired[str]
    detail: NotRequired[str]


class PartyLink(TypedDict):
    """Optional link to another party member or allied entity."""

    entity_id: str
    label: str
    status: Literal["active", "inactive", "temporary"]


class PlayerStateContract(TypedDict):
    """Top-level player state contract for gameplay and UI systems."""

    identity: PlayerIdentity
    race: str
    player_class: str
    background: str
    stats: list[PlayerStat]
    skills: list[PlayerSkill]
    inventory: list[InventoryItem]
    currencies: list[CurrencyBalance]
    status_effects: list[StatusEffect]
    current_location: LocationReference
    party_links: NotRequired[list[PartyLink]]
