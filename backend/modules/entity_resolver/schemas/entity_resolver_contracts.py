"""Contracts for generic entity resolution and user-input annotations."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


EntityType = Literal["item", "skill", "currency", "actor", "scene_entity", "interactable"]
CandidateSource = Literal[
    "inventory",
    "equipment",
    "held",
    "skills",
    "currencies",
    "actors",
    "scene_pool",
    "contextual",
]
ConfidenceBase = Literal["hard", "soft"]
TruthStatus = Literal["hard", "soft_scene", "plausible_contextual", "ambiguous", "unresolved"]
ExecutionStatus = Literal["clear", "interrupted_before_execution"]
ResolverStatus = Literal["clear", "has_unresolved", "has_ambiguous", "suspicious_failure"]


class TextSpan(TypedDict):
    """Exact character offsets inside the original raw input."""

    start: int
    end: int


class ResolverCandidate(TypedDict):
    """Generic candidate that can be matched against raw player input."""

    entity_type: EntityType
    entity_id: str
    name: str
    aliases: list[str]
    source: CandidateSource
    confidence_base: ConfidenceBase
    raw: dict[str, Any]


class ResolvedEntity(TypedDict):
    """Safely resolved entity mention for downstream canonical use."""

    source_text: str
    entity_type: EntityType
    entity_id: str
    canonical_name: str
    confidence: float
    match_method: str
    candidate_source: CandidateSource
    truth_status: Literal["hard", "soft_scene", "plausible_contextual"]
    span: TextSpan | None
    entity_data: dict[str, Any]


class AmbiguousMention(TypedDict):
    """Mention that could map to multiple candidates too closely to trust."""

    source_text: str
    span: TextSpan | None
    candidate_options: list[dict[str, Any]]
    confidence: float
    truth_status: Literal["ambiguous"]
    type_hint: NotRequired[str]
    reason: NotRequired[str]


class UnresolvedMention(TypedDict):
    """Likely explicit mention that cannot be safely mapped to a candidate."""

    source_text: str
    span: TextSpan | None
    expected_types: list[EntityType]
    truth_status: Literal["unresolved"]
    type_hint: NotRequired[str]
    reason: NotRequired[str]


class UserInputAnnotation(TypedDict):
    """Frontend-friendly text marking for exact resolved spans."""

    start: int
    end: int
    entity_type: EntityType
    entity_id: str
    display_text: str
    entity_data: dict[str, Any]


class EntityResolverDebug(TypedDict):
    """Lightweight resolver diagnostics for logs and the debug panel."""

    candidate_count: int
    candidate_sources_used: list[str]
    matches_considered: list[dict[str, Any]]
    semantic_resolver: dict[str, Any]
    resolver_status: ResolverStatus


class EntityResolutionResult(TypedDict):
    """Structured output of the resolver step."""

    raw_input: str
    resolved_entities: list[ResolvedEntity]
    unresolved_mentions: list[UnresolvedMention]
    ambiguous_mentions: list[AmbiguousMention]
    annotations: list[UserInputAnnotation]
    execution_status: ExecutionStatus
    resolver_status: ResolverStatus
    debug: EntityResolverDebug
