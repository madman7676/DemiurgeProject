"""LLM-assisted entity resolution and user-input annotation service."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any, Protocol

from backend.core.game_state.contracts import GameSessionState, SceneEntityPoolEntry
from backend.modules.entity_resolver.schemas.entity_resolver_contracts import (
    AmbiguousMention,
    EntityResolutionResult,
    ResolvedEntity,
    ResolverCandidate,
    TextSpan,
    UnresolvedMention,
    UserInputAnnotation,
)
from backend.modules.llm_connector.services.llm_client import LLMAdapter
from backend.modules.router.schemas.router_contracts import RouteDecision


logger = logging.getLogger(__name__)

WORD_SPLIT_PATTERN = re.compile(r"\s+")
TYPE_PRIORITY = {
    "held": 4,
    "equipment": 3,
    "inventory": 2,
    "actors": 2,
    "skills": 2,
    "currencies": 2,
    "scene_pool": 1,
    "contextual": 0,
}
ALL_ENTITY_TYPES = ["item", "skill", "currency", "actor", "scene_entity", "interactable"]


def _normalize_json_payload(raw_text: str) -> str:
    """Normalize optional markdown-wrapped JSON from an LLM helper."""

    cleaned = raw_text.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        logger.info("Removed markdown code fences from Entity Resolver response.")
        cleaned = cleaned[3:-3].strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    return cleaned


class SemanticEntityResolver(Protocol):
    """Optional LLM-backed resolver over bounded candidate lists."""

    def resolve(
        self,
        request: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Resolve requested entities from a compact request payload."""


class LLMSemanticEntityMatcher:
    """Use the existing LLM boundary to resolve entities from provided candidates only."""

    def __init__(self, llm_adapter: LLMAdapter) -> None:
        self._llm_adapter = llm_adapter

    def resolve(
        self,
        request: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Call the local LLM with a strict bounded entity-resolution task."""

        system_prompt = (
            "You are the Entity Resolver for a structured text adventure backend.\n"
            "You are a semantic bridge between player phrasing and available affordances.\n"
            "Ask: which available candidate best explains this player attempt?\n"
            "Compare player wording and routed method against each candidate's name, aliases, description, type, effect, usage semantics, costs, limits, and source.\n"
            "Support abbreviations, slang, translated names, partial names, paraphrased descriptions, described effects, intended outcomes, and indirect references.\n"
            "Do not treat router_output.entity_resolution_hint as a hard type constraint.\n"
            "Choose only from candidate_entities or mark the reference unresolved/ambiguous.\n"
            "Never invent entities, ids, names, locations, items, skills, actors, currencies, or interactables.\n"
            "Use router_output.expanded_player_intent and attempted_method as the primary semantic sources.\n"
            "Use raw_player_input mainly to preserve source_text for UI marking.\n"
            "Return strict JSON only. Do not use markdown. Do not add explanations outside JSON."
        )
        user_prompt = json.dumps(
            {
                "task": "Resolve implied or referenced entity/capability usage against provided candidates only.",
                "semantic_question": "Which available candidate best explains the player's attempted method or intended outcome?",
                "input_priority": [
                    "router_output.entity_resolution_hint",
                    "router_output.expanded_player_intent",
                    "router_output.attempted_method",
                    "router_output.primary_intent",
                    "raw_player_input",
                    "candidate_entities",
                ],
                "matching_guidance": [
                    "Do not rely primarily on exact names or aliases.",
                    "Use candidate descriptions, effects, usage semantics, costs, and limits when present.",
                    "If one candidate clearly explains the attempt, resolve it with confidence >= 0.70.",
                    "If several candidates plausibly explain the attempt, return ambiguous_mentions.",
                    "If no candidate explains the attempt, return unresolved_mentions.",
                    "Do not invent or transform candidate ids.",
                ],
                **request,
                "output_contract": {
                    "resolved_entities": [
                        {
                            "source_text": "",
                            "entity_type": "",
                            "entity_id": "",
                            "canonical_name": "",
                            "confidence": 0.0,
                            "reason": "",
                            "span_hint": "",
                        }
                    ],
                    "unresolved_mentions": [
                        {
                            "source_text": "",
                            "type_hint": "",
                            "reason": "",
                        }
                    ],
                    "ambiguous_mentions": [
                        {
                            "source_text": "",
                            "type_hint": "",
                            "candidates": [
                                {
                                    "entity_id": "",
                                    "canonical_name": "",
                                    "confidence": 0.0,
                                }
                            ],
                            "reason": "",
                        }
                    ],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        response = self._llm_adapter.generate_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            format_json=True,
        )
        raw_text = response.get("text", "")
        debug: dict[str, Any] = {
            "invoked": True,
            "used_mock": response.get("used_mock", False),
            "raw_response": raw_text[:1000],
        }
        if not raw_text.strip():
            debug["reason"] = "empty_llm_response"
            return self._empty_payload(), debug

        try:
            parsed = json.loads(_normalize_json_payload(raw_text))
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Entity Resolver LLM parse failure: %s. Raw response: %s", exc, raw_text)
            debug["reason"] = "parse_failure"
            return self._empty_payload(), debug

        if not isinstance(parsed, dict):
            debug["reason"] = "invalid_payload"
            return self._empty_payload(), debug
        return parsed, debug

    def _empty_payload(self) -> dict[str, Any]:
        return {
            "resolved_entities": [],
            "unresolved_mentions": [],
            "ambiguous_mentions": [],
        }


class EntityResolverService:
    """Resolve entity mentions against bounded candidate scopes only."""

    def __init__(self, semantic_matcher: SemanticEntityResolver | None = None) -> None:
        self._semantic_matcher = semantic_matcher

    def resolve_entities(
        self,
        raw_player_input: str,
        route_decision: RouteDecision,
        session_state: GameSessionState,
    ) -> EntityResolutionResult:
        """Resolve canonical entities and UI annotations from routed intent."""

        self.refresh_scene_entity_pool(session_state)
        candidates = self._build_candidates(session_state)
        provider_sources = self._collect_provider_sources(session_state)
        deterministic_resolved, deterministic_ambiguous, deterministic_debug = self._deterministic_prepass(
            raw_player_input=raw_player_input,
            route_decision=route_decision,
            candidates=candidates,
        )
        hint = route_decision.get("entity_resolution_hint", {"needed": False, "reason": ""})
        should_invoke_llm = bool(hint.get("needed")) or bool(deterministic_ambiguous)
        llm_payload: dict[str, Any] = {
            "resolved_entities": [],
            "unresolved_mentions": [],
            "ambiguous_mentions": [],
        }
        llm_debug: dict[str, Any] = {
            "invoked": False,
            "reason": "entity_resolution_hint_not_needed_and_deterministic_clear",
        }

        if should_invoke_llm:
            llm_payload, llm_debug = self._invoke_semantic_resolver(
                raw_player_input=raw_player_input,
                route_decision=route_decision,
                candidates=candidates,
            )

        resolved_entities, ambiguous_mentions, unresolved_mentions, validation_debug = self._build_result_lists(
            raw_player_input=raw_player_input,
            candidates=candidates,
            deterministic_resolved=deterministic_resolved,
            deterministic_ambiguous=deterministic_ambiguous,
            llm_payload=llm_payload,
        )
        if (
            bool(hint.get("needed"))
            and not resolved_entities
            and not ambiguous_mentions
            and not unresolved_mentions
        ):
            unresolved_mentions.append(
                self._fallback_unresolved_from_router_intent(raw_player_input, route_decision)
            )
            validation_debug["fallback_unresolved_from_router_intent"] = True

        resolver_status = self._resolver_status(
            hint_needed=bool(hint.get("needed")),
            resolved_entities=resolved_entities,
            unresolved_mentions=unresolved_mentions,
            ambiguous_mentions=ambiguous_mentions,
        )
        execution_status = (
            "interrupted_before_execution"
            if bool(hint.get("needed")) and resolver_status in {"has_unresolved", "has_ambiguous", "suspicious_failure"}
            else "clear"
        )
        annotations = self._build_annotations(raw_player_input, resolved_entities)

        result: EntityResolutionResult = {
            "raw_input": raw_player_input,
            "resolved_entities": resolved_entities,
            "unresolved_mentions": unresolved_mentions,
            "ambiguous_mentions": ambiguous_mentions,
            "annotations": annotations,
            "execution_status": execution_status,
            "resolver_status": resolver_status,
            "debug": {
                "candidate_count": len(candidates),
                "candidate_sources_used": provider_sources,
                "matches_considered": deterministic_debug,
                "semantic_resolver": {
                    **llm_debug,
                    "validation": validation_debug,
                    "hint": hint,
                },
                "resolver_status": resolver_status,
            },
        }
        self._log_resolution(result)
        return result

    def refresh_scene_entity_pool(
        self,
        session_state: GameSessionState,
        narrative_text: str = "",
        resolved_entities: list[ResolvedEntity] | None = None,
        time_advanced: int = 0,
    ) -> None:
        """Refresh scene-memory anchors without parsing language-specific text."""

        current_location = session_state["player_state"]["current_location"]
        anchor = session_state["scene_pool_anchor"]
        location_changed = (
            anchor["region_id"] != current_location.get("region_id", "")
            or anchor["detail"] != current_location.get("detail", "")
        )
        if location_changed or time_advanced >= 60:
            session_state["scene_entity_pool"] = []
            session_state["scene_pool"] = session_state["scene_entity_pool"]  # type: ignore[typeddict-unknown-key]

        pool_entries = self._session_scene_pool(session_state)
        for resolved_entity in resolved_entities or []:
            if resolved_entity["truth_status"] != "soft_scene":
                continue
            self._ensure_scene_entry(
                pool_entries,
                entity_type=resolved_entity["entity_type"],
                entity_id=resolved_entity["entity_id"],
                name=resolved_entity["canonical_name"],
                aliases=[resolved_entity["source_text"]],
                source="resolved_scene",
            )

        session_state["scene_pool_anchor"] = {
            "region_id": str(current_location.get("region_id", "place")),
            "detail": str(current_location.get("detail", "")).strip(),
            "turn": session_state["turn_count"],
        }
        session_state["scene_entity_pool"] = pool_entries
        session_state["scene_pool"] = pool_entries  # type: ignore[typeddict-unknown-key]

    def _build_candidates(self, session_state: GameSessionState) -> list[ResolverCandidate]:
        """Collect candidates from bounded local scopes only."""

        player_state = session_state["player_state"]
        candidates: list[ResolverCandidate] = []
        candidates.extend(self._build_item_candidates(player_state.get("held_items", []), "held"))
        candidates.extend(self._build_item_candidates(player_state.get("equipped_items", []), "equipment"))
        candidates.extend(self._build_item_candidates(player_state.get("inventory", []), "inventory"))
        candidates.extend(self._build_skill_candidates(player_state.get("skills", [])))
        candidates.extend(self._build_currency_candidates(player_state.get("currencies", [])))
        candidates.extend(self._build_actor_candidates(session_state))
        candidates.extend(
            self._build_scene_pool_candidates(
                self._session_scene_pool(session_state)
            )
        )
        candidates.extend(self._build_explicit_contextual_candidates(session_state))
        return self._dedupe_candidates(candidates)

    def _session_scene_pool(self, session_state: GameSessionState) -> list[SceneEntityPoolEntry]:
        """Read the current scene pool while preserving legacy key compatibility."""

        scene_pool = session_state.get("scene_pool", [])  # type: ignore[typeddict-unknown-key]
        legacy_pool = session_state.get("scene_entity_pool", [])
        if isinstance(scene_pool, list) and scene_pool:
            return scene_pool
        return legacy_pool if isinstance(legacy_pool, list) else []

    def _collect_provider_sources(self, session_state: GameSessionState) -> list[str]:
        """Report enabled provider scopes before canonical de-duplication."""

        player_state = session_state["player_state"]
        sources: set[str] = set()
        if player_state.get("held_items"):
            sources.add("held")
        if player_state.get("equipped_items"):
            sources.add("equipment")
        if player_state.get("inventory"):
            sources.add("inventory")
        if player_state.get("skills"):
            sources.add("skills")
        if player_state.get("currencies"):
            sources.add("currencies")
        if self._build_actor_candidates(session_state):
            sources.add("actors")
        if self._session_scene_pool(session_state):
            sources.add("scene_pool")
        if self._build_explicit_contextual_candidates(session_state):
            sources.add("contextual")
        return sorted(sources)

    def _build_item_candidates(self, items: list[dict[str, Any]], source: str) -> list[ResolverCandidate]:
        return [
            {
                "entity_type": "item",
                "entity_id": item["item_id"],
                "name": item["name"],
                "aliases": self._build_aliases(item.get("name", ""), item.get("aliases", [])),
                "source": source,  # type: ignore[typeddict-item]
                "confidence_base": "hard",
                "raw": item,
            }
            for item in items
            if item.get("item_id") and item.get("name")
        ]

    def _build_skill_candidates(self, skills: list[dict[str, Any]]) -> list[ResolverCandidate]:
        return [
            {
                "entity_type": "skill",
                "entity_id": skill["skill_id"],
                "name": skill["name"],
                "aliases": self._build_aliases(skill.get("name", ""), skill.get("aliases", [])),
                "source": "skills",
                "confidence_base": "hard",
                "raw": skill,
            }
            for skill in skills
            if skill.get("skill_id") and skill.get("name")
        ]

    def _build_currency_candidates(self, currencies: list[dict[str, Any]]) -> list[ResolverCandidate]:
        return [
            {
                "entity_type": "currency",
                "entity_id": currency["currency_id"],
                "name": currency["name"],
                "aliases": self._build_aliases(currency.get("name", ""), currency.get("aliases", [])),
                "source": "currencies",
                "confidence_base": "hard",
                "raw": currency,
            }
            for currency in currencies
            if currency.get("currency_id") and currency.get("name")
        ]

    def _build_actor_candidates(self, session_state: GameSessionState) -> list[ResolverCandidate]:
        player_region = session_state["player_state"]["current_location"]["region_id"]
        return [
            {
                "entity_type": "actor",
                "entity_id": npc["identity"]["npc_id"],
                "name": npc["identity"]["name"],
                "aliases": self._build_aliases(
                    npc["identity"]["name"],
                    npc["identity"].get("aliases", []) + [npc["role"]],
                ),
                "source": "actors",
                "confidence_base": "hard",
                "raw": npc,
            }
            for npc in session_state.get("npc_states", [])
            if npc["location"]["region_id"] == player_region
        ]

    def _build_scene_pool_candidates(self, scene_entity_pool: list[SceneEntityPoolEntry]) -> list[ResolverCandidate]:
        return [
            {
                "entity_type": entry["entity_type"],
                "entity_id": entry["entity_id"],
                "name": entry["name"],
                "aliases": self._build_aliases(entry["name"], entry.get("aliases", [])),
                "source": "scene_pool",
                "confidence_base": "soft",
                "raw": entry["raw"],
            }
            for entry in scene_entity_pool
            if entry.get("entity_id") and entry.get("name")
        ]

    def _build_explicit_contextual_candidates(self, session_state: GameSessionState) -> list[ResolverCandidate]:
        """Use only explicit contextual candidates if external state provides them."""

        candidates: list[ResolverCandidate] = []
        for entry in session_state.get("contextual_candidates", []):  # type: ignore[typeddict-item]
            entity_type = entry.get("entity_type")
            entity_id = entry.get("entity_id")
            name = entry.get("name")
            if entity_type not in {"scene_entity", "interactable"} or not entity_id or not name:
                continue
            candidates.append(
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "name": name,
                    "aliases": self._build_aliases(name, entry.get("aliases", [])),
                    "source": "contextual",
                    "confidence_base": "soft",
                    "raw": entry.get("raw", entry),
                }
            )
        return candidates

    def _dedupe_candidates(self, candidates: list[ResolverCandidate]) -> list[ResolverCandidate]:
        """Keep one best candidate per canonical entity while preserving source priority."""

        deduped: dict[tuple[str, str], ResolverCandidate] = {}
        for candidate in candidates:
            key = (candidate["entity_type"], candidate["entity_id"])
            existing = deduped.get(key)
            if existing is None or TYPE_PRIORITY.get(candidate["source"], 0) > TYPE_PRIORITY.get(existing["source"], 0):
                deduped[key] = candidate
        return list(deduped.values())

    def _build_aliases(self, canonical_name: str, explicit_aliases: list[str]) -> list[str]:
        """Build an alias set from structured data only."""

        aliases = {str(alias).strip() for alias in explicit_aliases if str(alias).strip()}
        if canonical_name.strip():
            aliases.add(canonical_name.strip())
        return sorted(aliases)

    def _deterministic_prepass(
        self,
        raw_player_input: str,
        route_decision: RouteDecision,
        candidates: list[ResolverCandidate],
    ) -> tuple[list[ResolvedEntity], list[AmbiguousMention], list[dict[str, Any]]]:
        """Fast exact/simple matching without language-specific entity parsing."""

        search_sources = [
            ("raw_player_input", raw_player_input),
            ("expanded_player_intent", route_decision["expanded_player_intent"]),
            ("primary_intent", route_decision["primary_intent"]),
        ]
        match_records: list[dict[str, Any]] = []
        for candidate in candidates:
            best_match = self._best_deterministic_candidate_match(candidate, search_sources, raw_player_input)
            if best_match is None:
                continue
            match_records.append({**best_match, "candidate": candidate})

        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in match_records:
            grouped.setdefault(record["source_text_norm"], []).append(record)

        resolved: list[ResolvedEntity] = []
        ambiguous: list[AmbiguousMention] = []
        debug: list[dict[str, Any]] = []
        for records in grouped.values():
            ranked = sorted(
                records,
                key=lambda item: (
                    item["confidence"],
                    TYPE_PRIORITY.get(item["candidate"]["source"], 0),
                ),
                reverse=True,
            )
            best = ranked[0]
            close = len(ranked) > 1 and best["confidence"] - ranked[1]["confidence"] < 0.15
            debug.extend(
                {
                    "source_text": record["source_text"],
                    "entity_id": record["candidate"]["entity_id"],
                    "entity_type": record["candidate"]["entity_type"],
                    "candidate_source": record["candidate"]["source"],
                    "confidence": round(record["confidence"], 3),
                    "match_method": record["match_method"],
                    "truth_status": self._truth_status_for_candidate(record["candidate"]),
                }
                for record in ranked[:3]
            )
            if close:
                ambiguous.append(self._ambiguous_from_ranked(best["source_text"], best["span"], ranked))
                continue
            resolved.append(self._resolved_from_candidate(best["source_text"], best["span"], best["candidate"], best["confidence"], best["match_method"]))

        resolved.sort(key=lambda entity: entity["span"]["start"] if entity["span"] else 10**9)
        ambiguous.sort(key=lambda mention: mention["span"]["start"] if mention["span"] else 10**9)
        return resolved, ambiguous, sorted(debug, key=lambda item: item["confidence"], reverse=True)[:20]

    def _best_deterministic_candidate_match(
        self,
        candidate: ResolverCandidate,
        search_sources: list[tuple[str, str]],
        raw_player_input: str,
    ) -> dict[str, Any] | None:
        terms = [candidate["entity_id"], candidate["name"], *candidate["aliases"]]
        best: dict[str, Any] | None = None
        for term in terms:
            normalized_term = self._normalize_text(term)
            if not normalized_term:
                continue
            for source_name, text in search_sources:
                normalized_text = self._normalize_text(text)
                if not normalized_text:
                    continue
                confidence = 0.0
                method = ""
                if normalized_text == normalized_term:
                    confidence = 0.99
                    method = f"exact_{source_name}"
                elif self._contains_normalized_phrase(normalized_text, normalized_term):
                    confidence = 0.93 if source_name == "raw_player_input" else 0.88
                    method = f"normalized_{source_name}"
                if not confidence:
                    continue

                source_text = self._display_text_for_term(raw_player_input, text, term)
                span = self._find_span(raw_player_input, source_text)
                if best is None or confidence > best["confidence"]:
                    best = {
                        "source_text": source_text,
                        "source_text_norm": self._normalize_text(source_text),
                        "span": span,
                        "confidence": confidence,
                        "match_method": method,
                    }
        return best

    def _contains_normalized_phrase(self, normalized_text: str, normalized_term: str) -> bool:
        return f" {normalized_term} " in f" {normalized_text} "

    def _display_text_for_term(self, raw_player_input: str, matched_text: str, term: str) -> str:
        raw_span = self._find_span(raw_player_input, term)
        if raw_span is not None:
            return raw_player_input[raw_span["start"] : raw_span["end"]]
        return term if term else matched_text

    def _invoke_semantic_resolver(
        self,
        raw_player_input: str,
        route_decision: RouteDecision,
        candidates: list[ResolverCandidate],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if self._semantic_matcher is None:
            return {
                "resolved_entities": [],
                "unresolved_mentions": [],
                "ambiguous_mentions": [],
            }, {"invoked": False, "reason": "no_semantic_matcher"}

        request = {
            "raw_player_input": raw_player_input,
            "router_output": {
                "entity_resolution_hint": route_decision.get("entity_resolution_hint", {"needed": False, "reason": ""}),
                "expanded_player_intent": route_decision["expanded_player_intent"],
                "primary_intent": route_decision["primary_intent"],
                "attempted_method": route_decision.get("attempted_method", ""),
                "action_category": route_decision["action_category"],
                "possible_targets": route_decision["possible_targets"],
            },
            "candidate_entities": [
                self._candidate_semantic_summary(candidate)
                for candidate in candidates
            ],
        }
        return self._semantic_matcher.resolve(request)

    def _candidate_semantic_summary(self, candidate: ResolverCandidate) -> dict[str, Any]:
        """Send compact affordance data to the semantic resolver."""

        raw = candidate["raw"] if isinstance(candidate["raw"], dict) else {}
        return {
            "entity_type": candidate["entity_type"],
            "entity_id": candidate["entity_id"],
            "name": candidate["name"],
            "aliases": candidate["aliases"],
            "source": candidate["source"],
            "confidence_base": candidate["confidence_base"],
            "description": self._compact_value(raw.get("description", "")),
            "effect": self._compact_value(raw.get("effect", raw.get("effects", ""))),
            "usage": self._compact_value(raw.get("usage", raw.get("use", raw.get("usage_semantics", "")))),
            "costs": self._compact_value(raw.get("costs", raw.get("cost", ""))),
            "limits": self._compact_value(raw.get("limits", raw.get("limitations", ""))),
            "tags": raw.get("tags", []) if isinstance(raw.get("tags", []), list) else [],
            "quantity": raw.get("quantity"),
            "level": raw.get("level"),
        }

    def _compact_value(self, value: object) -> object:
        """Keep candidate semantic fields readable but bounded."""

        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, list):
            return value[:8]
        if isinstance(value, dict):
            return {str(key): value[key] for key in list(value)[:12]}
        return str(value)[:300]

    def _build_result_lists(
        self,
        raw_player_input: str,
        candidates: list[ResolverCandidate],
        deterministic_resolved: list[ResolvedEntity],
        deterministic_ambiguous: list[AmbiguousMention],
        llm_payload: dict[str, Any],
    ) -> tuple[list[ResolvedEntity], list[AmbiguousMention], list[UnresolvedMention], dict[str, Any]]:
        candidate_index = {
            (candidate["entity_type"], candidate["entity_id"]): candidate
            for candidate in candidates
        }
        resolved_by_key: dict[tuple[str, str], ResolvedEntity] = {
            (entity["entity_type"], entity["entity_id"]): entity
            for entity in deterministic_resolved
        }
        ambiguous_mentions = list(deterministic_ambiguous)
        unresolved_mentions: list[UnresolvedMention] = []
        invalid_resolved_ids: list[dict[str, Any]] = []

        for raw_entity in self._safe_list(llm_payload.get("resolved_entities", [])):
            if not isinstance(raw_entity, dict):
                continue
            entity_type = str(raw_entity.get("entity_type", ""))
            entity_id = str(raw_entity.get("entity_id", ""))
            candidate = candidate_index.get((entity_type, entity_id))
            source_text = str(raw_entity.get("source_text", "")).strip() or str(raw_entity.get("span_hint", "")).strip()
            if candidate is None:
                invalid_resolved_ids.append(
                    {
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "source_text": source_text,
                    }
                )
                if source_text:
                    unresolved_mentions.append(
                        self._unresolved_from_text(raw_player_input, source_text, entity_type, "LLM returned an entity id outside the provided candidates.")
                    )
                continue
            confidence = self._safe_confidence(raw_entity.get("confidence", 0.0))
            if confidence < 0.7:
                unresolved_mentions.append(
                    self._unresolved_from_text(
                        raw_player_input=raw_player_input,
                        source_text=source_text or candidate["name"],
                        type_hint=entity_type,
                        reason="Semantic resolver confidence was below the safe resolution threshold.",
                    )
                )
                continue
            span = self._find_span(raw_player_input, source_text)
            resolved_by_key[(candidate["entity_type"], candidate["entity_id"])] = self._resolved_from_candidate(
                source_text=source_text or candidate["name"],
                span=span,
                candidate=candidate,
                confidence=confidence,
                match_method="semantic_llm",
            )

        for raw_ambiguous in self._safe_list(llm_payload.get("ambiguous_mentions", [])):
            if not isinstance(raw_ambiguous, dict):
                continue
            source_text = str(raw_ambiguous.get("source_text", "")).strip()
            options = []
            for option in self._safe_list(raw_ambiguous.get("candidates", [])):
                if not isinstance(option, dict):
                    continue
                candidate = self._candidate_by_id(candidates, str(option.get("entity_id", "")))
                if candidate is None:
                    invalid_resolved_ids.append(
                        {
                            "entity_id": str(option.get("entity_id", "")),
                            "source_text": source_text,
                            "ambiguous": True,
                        }
                    )
                    continue
                options.append(
                    {
                        "entity_id": candidate["entity_id"],
                        "name": candidate["name"],
                        "entity_type": candidate["entity_type"],
                        "candidate_source": candidate["source"],
                        "confidence": self._safe_confidence(option.get("confidence", 0.0)),
                        "truth_status": self._truth_status_for_candidate(candidate),
                    }
                )
            if options:
                options.sort(key=lambda item: item["confidence"], reverse=True)
                ambiguous_mentions.append(
                    {
                        "source_text": source_text,
                        "span": self._find_span(raw_player_input, source_text),
                        "candidate_options": options[:3],
                        "confidence": options[0]["confidence"],
                        "truth_status": "ambiguous",
                        "type_hint": str(raw_ambiguous.get("type_hint", "")),
                        "reason": str(raw_ambiguous.get("reason", "")),
                    }
                )

        for raw_unresolved in self._safe_list(llm_payload.get("unresolved_mentions", [])):
            if not isinstance(raw_unresolved, dict):
                continue
            source_text = str(raw_unresolved.get("source_text", "")).strip()
            if not source_text:
                continue
            unresolved_mentions.append(
                self._unresolved_from_text(
                    raw_player_input=raw_player_input,
                    source_text=source_text,
                    type_hint=str(raw_unresolved.get("type_hint", "")),
                    reason=str(raw_unresolved.get("reason", "")),
                )
            )

        resolved_entities = sorted(
            resolved_by_key.values(),
            key=lambda entity: entity["span"]["start"] if entity["span"] else 10**9,
        )
        ambiguous_mentions.sort(key=lambda mention: mention["span"]["start"] if mention["span"] else 10**9)
        unresolved_mentions = self._dedupe_unresolved(unresolved_mentions, resolved_entities, ambiguous_mentions)
        return resolved_entities, ambiguous_mentions, unresolved_mentions, {
            "invalid_or_invented_ids": invalid_resolved_ids,
        }

    def _resolved_from_candidate(
        self,
        source_text: str,
        span: TextSpan | None,
        candidate: ResolverCandidate,
        confidence: float,
        match_method: str,
    ) -> ResolvedEntity:
        return {
            "source_text": source_text,
            "entity_type": candidate["entity_type"],
            "entity_id": candidate["entity_id"],
            "canonical_name": candidate["name"],
            "confidence": round(max(0.0, min(1.0, confidence)), 3),
            "match_method": match_method,
            "candidate_source": candidate["source"],
            "truth_status": self._truth_status_for_candidate(candidate),
            "span": span,
            "entity_data": candidate["raw"],
        }

    def _ambiguous_from_ranked(
        self,
        source_text: str,
        span: TextSpan | None,
        ranked: list[dict[str, Any]],
    ) -> AmbiguousMention:
        return {
            "source_text": source_text,
            "span": span,
            "candidate_options": [
                {
                    "entity_id": record["candidate"]["entity_id"],
                    "name": record["candidate"]["name"],
                    "entity_type": record["candidate"]["entity_type"],
                    "candidate_source": record["candidate"]["source"],
                    "confidence": round(record["confidence"], 3),
                    "truth_status": self._truth_status_for_candidate(record["candidate"]),
                }
                for record in ranked[:3]
            ],
            "confidence": round(ranked[0]["confidence"], 3),
            "truth_status": "ambiguous",
        }

    def _unresolved_from_text(
        self,
        raw_player_input: str,
        source_text: str,
        type_hint: str,
        reason: str,
    ) -> UnresolvedMention:
        return {
            "source_text": source_text,
            "span": self._find_span(raw_player_input, source_text),
            "expected_types": self._expected_types_from_hint(type_hint),
            "truth_status": "unresolved",
            "type_hint": type_hint,
            "reason": reason,
        }

    def _fallback_unresolved_from_router_intent(
        self,
        raw_player_input: str,
        route_decision: RouteDecision,
    ) -> UnresolvedMention:
        source_text = route_decision["expanded_player_intent"].strip() or route_decision["primary_intent"].strip() or raw_player_input
        return self._unresolved_from_text(
            raw_player_input=raw_player_input,
            source_text=source_text,
            type_hint="",
            reason="Entity resolution was requested, but the resolver returned no entity decision.",
        )

    def _expected_types_from_hint(self, type_hint: str) -> list[str]:
        normalized = type_hint.strip()
        if normalized in ALL_ENTITY_TYPES:
            return [normalized]
        return list(ALL_ENTITY_TYPES)

    def _candidate_by_id(self, candidates: list[ResolverCandidate], entity_id: str) -> ResolverCandidate | None:
        for candidate in candidates:
            if candidate["entity_id"] == entity_id:
                return candidate
        return None

    def _safe_list(self, value: object) -> list[object]:
        return value if isinstance(value, list) else []

    def _safe_confidence(self, value: object) -> float:
        try:
            return round(max(0.0, min(1.0, float(value))), 3)
        except (TypeError, ValueError):
            return 0.0

    def _dedupe_unresolved(
        self,
        unresolved_mentions: list[UnresolvedMention],
        resolved_entities: list[ResolvedEntity],
        ambiguous_mentions: list[AmbiguousMention],
    ) -> list[UnresolvedMention]:
        occupied = [
            entity["span"] for entity in resolved_entities if entity["span"] is not None
        ] + [
            mention["span"] for mention in ambiguous_mentions if mention["span"] is not None
        ]
        deduped: list[UnresolvedMention] = []
        seen = set()
        for mention in unresolved_mentions:
            span = mention["span"]
            if span is not None and any(self._spans_overlap((span["start"], span["end"]), (used["start"], used["end"])) for used in occupied):
                continue
            key = (self._normalize_text(mention["source_text"]), mention.get("type_hint", ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(mention)
        return deduped

    def _resolver_status(
        self,
        hint_needed: bool,
        resolved_entities: list[ResolvedEntity],
        unresolved_mentions: list[UnresolvedMention],
        ambiguous_mentions: list[AmbiguousMention],
    ) -> str:
        if ambiguous_mentions:
            return "has_ambiguous"
        if unresolved_mentions:
            return "has_unresolved"
        if hint_needed and not resolved_entities:
            return "suspicious_failure"
        return "clear"

    def _build_annotations(self, raw_input: str, resolved_entities: list[ResolvedEntity]) -> list[UserInputAnnotation]:
        annotations: list[UserInputAnnotation] = []
        for entity in resolved_entities:
            span = entity["span"]
            if span is None:
                continue
            annotations.append(
                {
                    "start": span["start"],
                    "end": span["end"],
                    "entity_type": entity["entity_type"],
                    "entity_id": entity["entity_id"],
                    "display_text": raw_input[span["start"] : span["end"]],
                    "entity_data": entity["entity_data"],
                }
            )
        return annotations

    def _ensure_scene_entry(
        self,
        scene_entity_pool: list[SceneEntityPoolEntry],
        entity_type: str,
        entity_id: str,
        name: str,
        aliases: list[str],
        source: str,
    ) -> None:
        if any(entry["entity_id"] == entity_id for entry in scene_entity_pool):
            return
        scene_entity_pool.append(
            {
                "entity_type": entity_type,  # type: ignore[typeddict-item]
                "entity_id": entity_id,
                "name": name,
                "aliases": sorted({alias for alias in aliases if alias}),
                "source": source,
                "raw": {"source": source},
            }
        )

    def _find_span(self, raw_input: str, source_text: str) -> TextSpan | None:
        if not source_text:
            return None
        start = raw_input.casefold().find(source_text.casefold())
        if start < 0:
            return None
        return {"start": start, "end": start + len(source_text)}

    def _normalize_text(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value)).casefold()
        normalized = "".join(character for character in normalized if not unicodedata.combining(character))
        normalized = re.sub(r"[^\w\s'-]", " ", normalized, flags=re.UNICODE)
        normalized = WORD_SPLIT_PATTERN.sub(" ", normalized).strip()
        return normalized

    def _slugify(self, value: str) -> str:
        return self._normalize_text(value).replace(" ", "_") or "scene_entity"

    def _truth_status_for_candidate(self, candidate: ResolverCandidate) -> str:
        if candidate["source"] == "scene_pool":
            return "soft_scene"
        if candidate["source"] == "contextual":
            return "plausible_contextual"
        return "hard"

    def _spans_overlap(self, left: tuple[int, int], right: tuple[int, int]) -> bool:
        return not (left[1] <= right[0] or right[1] <= left[0])

    def _log_resolution(self, result: EntityResolutionResult) -> None:
        logger.info(
            (
                "Entity resolver:\n"
                "  resolver_status=%s execution_status=%s\n"
                "  candidate_count=%s\n"
                "  sources=%s\n"
                "  semantic=%s\n"
                "  resolved=%s\n"
                "  ambiguous=%s\n"
                "  unresolved=%s"
            ),
            result["resolver_status"],
            result["execution_status"],
            result["debug"]["candidate_count"],
            result["debug"]["candidate_sources_used"],
            {
                "invoked": result["debug"]["semantic_resolver"].get("invoked"),
                "reason": result["debug"]["semantic_resolver"].get("reason"),
                "validation": result["debug"]["semantic_resolver"].get("validation"),
            },
            [
                {
                    "text": entity["source_text"],
                    "entity_id": entity["entity_id"],
                    "confidence": entity["confidence"],
                    "match_method": entity["match_method"],
                    "truth_status": entity["truth_status"],
                }
                for entity in result["resolved_entities"]
            ],
            result["ambiguous_mentions"],
            result["unresolved_mentions"],
        )
