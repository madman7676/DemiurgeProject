"""End-to-end exploration-mode processing pipeline."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

from backend.core.game_state.contracts import DecisionCycle, DecisionEvent
from backend.core.game_state.services.consequence_service import apply_consequence_layer
from backend.core.game_state.services.session_service import (
    InMemorySessionStore,
    append_decision_cycle,
    append_message,
    build_visible_state,
)
from backend.core.game_state.services.scene_memory_service import apply_narrator_scene_memory
from backend.core.game_state.services.state_update_service import apply_state_updates
from backend.modules.action_evaluation.schemas.action_evaluation_contracts import (
    ActionProcessingContract,
)
from backend.modules.action_evaluation.services.action_evaluation_service import (
    ActionEvaluationService,
)
from backend.modules.entity_resolver.schemas.entity_resolver_contracts import (
    EntityResolutionResult,
)
from backend.modules.entity_resolver.services.entity_resolver_service import (
    EntityResolverService,
)
from backend.modules.feature_modules.services.feature_registry import build_available_modules
from backend.modules.narrator.services.narrator_service import (
    NarratorService,
    detect_output_language,
    extract_available_entities,
    extract_narrator_mentions,
    store_scene_candidates,
)
from backend.modules.router.schemas.router_contracts import (
    RouteDecision,
    RouterAgentInput,
)
from backend.modules.router.services.router_service import RouterService
from backend.modules.world_evolution.schemas.world_evolution_contracts import (
    WorldEvolutionCheckResult,
)
from backend.modules.world_evolution.services.world_evolution_service import (
    check_world_evolution_hook,
)


class ExplorationPipelineResult(TypedDict):
    """Response payload produced by the exploration pipeline."""

    route: RouteDecision
    entity_resolution: EntityResolutionResult
    action_result: ActionProcessingContract
    narrative_text: str
    visible_state: dict
    evolution_check: WorldEvolutionCheckResult
    recent_messages: list[dict]
    decision_cycle: DecisionCycle
    decision_history: list[DecisionCycle]


class ExplorationPipeline:
    """Coordinates the first minimal exploration-only gameplay loop."""

    def __init__(
        self,
        session_store: InMemorySessionStore,
        router_service: RouterService,
        entity_resolver_service: EntityResolverService,
        action_evaluation_service: ActionEvaluationService,
        narrator_service: NarratorService,
    ) -> None:
        self._session_store = session_store
        self._router_service = router_service
        self._entity_resolver_service = entity_resolver_service
        self._action_evaluation_service = action_evaluation_service
        self._narrator_service = narrator_service

    def process_player_message(
        self,
        raw_player_input: str,
        on_narration_chunk=None,
        on_status: Callable[[str], None] | None = None,
        on_pipeline_update: Callable[[dict], None] | None = None,
    ) -> ExplorationPipelineResult:
        """Process one exploration action from input to visible frontend result."""

        def emit_status(step: str) -> None:
            if on_status:
                on_status(step)

        def emit_update(step: str, payload: dict) -> None:
            if on_pipeline_update:
                on_pipeline_update({"step": step, "turn": cycle_turn, **payload})

        session_state = self._session_store.get_session()
        if not session_state.get("output_language"):
            session_state["output_language"] = detect_output_language(raw_player_input, fallback="uk")
        cycle_turn = session_state["turn_count"] + 1
        decision_events: list[DecisionEvent] = []

        active_features = [
            feature["feature_id"]
            for feature in session_state["world_rules"]["active_features"]
            if feature["enabled"]
        ]
        router_input: RouterAgentInput = {
            "raw_player_input": raw_player_input,
            "game_mode": session_state["mode"],
            "scene_context": {
                "game_mode": session_state["mode"],
                "location": session_state["player_state"]["current_location"].get(
                    "detail",
                    session_state["player_state"]["current_location"]["region_id"],
                ),
                "time_summary": (
                    f"day {session_state['current_time']['day']} "
                    f"{session_state['current_time']['hour']:02d}:{session_state['current_time']['minute']:02d}"
                ),
            },
            "visible_entities_summary": [
                {
                    "entity_id": npc["identity"]["npc_id"],
                    "name": npc["identity"]["name"],
                    "role": npc["role"],
                }
                for npc in session_state["npc_states"]
                if npc["location"]["region_id"]
                == session_state["player_state"]["current_location"]["region_id"]
            ],
            "available_modules": build_available_modules(active_features),
            "last_presented_choices": session_state["last_presented_choices"],
            "active_features": active_features,
        }

        emit_status("router")
        route = self._router_service.route_message(router_input)
        router_event: DecisionEvent = {
                "source": "router",
                "message": f"Expanded intent routed as {route['primary_intent']}.",
                "details": {
                    "action_category": route["action_category"],
                    "raw_player_input": raw_player_input,
                    "expanded_player_intent": route["expanded_player_intent"],
                    "primary_intent": route["primary_intent"],
                    "attempted_method": route.get("attempted_method", ""),
                    "secondary_elements": route["secondary_elements"],
                    "possible_targets": route["possible_targets"],
                    "requested_agents": route["requested_agents"],
                    "narration_notes": route["narration_notes"],
                    "routing_reason": route["routing_reason"],
                    "entity_resolution_hint": route["entity_resolution_hint"],
                },
            }
        decision_events.append(router_event)
        emit_update(
            "router",
            {
                "event": router_event,
                "route": route,
                "decision_events": list(decision_events),
            },
        )
        # Entity resolution is intentionally quiet in the player UI for now; debug panel still captures details.
        entity_resolution = self._entity_resolver_service.resolve_entities(
            raw_player_input=raw_player_input,
            route_decision=route,
            session_state=session_state,
        )
        entity_resolver_event: DecisionEvent = {
                "source": "entity_resolver",
                "message": "Resolved canonical entity references from raw input.",
                "details": {
                    "execution_status": entity_resolution["execution_status"],
                    "resolver_status": entity_resolution["resolver_status"],
                    "resolved_entities": entity_resolution["resolved_entities"],
                    "ambiguous_mentions": entity_resolution["ambiguous_mentions"],
                    "unresolved_mentions": entity_resolution["unresolved_mentions"],
                    "annotations": entity_resolution["annotations"],
                    "debug": entity_resolution["debug"],
                },
            }
        decision_events.append(entity_resolver_event)
        emit_update(
            "entity_resolver",
            {
                "event": entity_resolver_event,
                "entity_resolution": entity_resolution,
                "user_message": {
                    "role": "player",
                    "text": raw_player_input,
                    "annotations": entity_resolution["annotations"],
                },
                "decision_events": list(decision_events),
            },
        )
        emit_status("judge")
        action_result = self._action_evaluation_service.evaluate_action(
            raw_player_input=raw_player_input,
            route_decision=route,
            entity_resolution=entity_resolution,
            session_state=session_state,
        )
        judge_event: DecisionEvent = {
                "source": "action_evaluation",
                "message": "Judge resolved the attempted action.",
                "details": {
                    "raw_player_input": action_result["raw_player_input"],
                    "expanded_player_intent": action_result["expanded_player_intent"],
                    "action_result": action_result["action_result"],
                    "outcome_quality": action_result["outcome_quality"],
                    "attempt_summary": action_result["attempt_summary"],
                    "blockers": action_result["blockers"],
                    "side_effects": action_result["proposed_side_effects"],
                    "reasoning_short": action_result["reasoning_short"],
                },
            }
        decision_events.append(judge_event)
        emit_update(
            "judge",
            {
                "event": judge_event,
                "result": action_result,
                "decision_events": list(decision_events),
            },
        )
        emit_status("time")
        if "interrupted_before_execution" in action_result["risk_flags"]:
            session_state["interruption_pressure"] += 1
        else:
            session_state["interruption_pressure"] = max(
                0,
                session_state["interruption_pressure"] - 1,
            )
        decision_events.append(
            {
                "source": "time_cost",
                "message": "Assigned in-world time cost.",
                "details": {
                    "duration_class": action_result["time_hints"]["duration_class"],
                    "effort_level": action_result["time_hints"]["effort_level"],
                    "interrupted": action_result["time_hints"]["interrupted"],
                    "amount": action_result["time_cost"]["amount"],
                    "unit": action_result["time_cost"]["unit"],
                },
            }
        )
        emit_status("consequence")
        action_result = apply_consequence_layer(
            session_state=session_state,
            action_result=action_result,
            action_category=route["action_category"],
        )
        if action_result["npc_reactions"]:
            first_reaction = action_result["npc_reactions"][0]
            decision_events.append(
                {
                    "source": "npc_reaction",
                    "message": "A nearby NPC reacted to the action.",
                    "details": {
                        "npc_id": first_reaction["npc_id"],
                        "reaction_type": first_reaction["reaction_type"],
                    },
                }
            )
        else:
            decision_events.append(
                {
                    "source": "npc_reaction",
                    "message": "No nearby NPC crossed the interest threshold for reaction.",
                    "details": {},
                }
            )
        decision_events.append(
            {
                "source": "consequence",
                "message": "Determined the main outcome summary.",
                "details": {
                    "outcome_quality": action_result["outcome_quality"],
                    "quality_side_effect_chance": action_result["quality_side_effect_chance"],
                    "quality_side_effect_applied": action_result["quality_side_effect_applied"],
                    "proposed_side_effects": action_result["proposed_side_effects"],
                    "applied_side_effects": action_result["applied_side_effects"],
                    "side_effects": action_result["side_effects"],
                    "revealed_information": action_result["revealed_information"],
                    "risk_flags": action_result["risk_flags"],
                    "state_intents": action_result["state_intents"],
                    "outcome_summary": action_result["outcome_summary"],
                },
            }
        )
        action_result = apply_state_updates(session_state, action_result)
        decision_events.append(
            {
                "source": "state_update",
                "message": "Applied visible state changes.",
                "details": {
                    "changes": [change["summary"] for change in action_result["state_changes"]],
                },
            }
        )
        evolution_check = check_world_evolution_hook(session_state)
        decision_events.append(
            {
                "source": "world_evolution",
                "message": evolution_check["note"],
                "details": {
                    "threshold_reached": evolution_check["threshold_reached"],
                },
            }
        )
        emit_status("narrator")
        visible_state = build_visible_state(session_state)
        decision_events.append(
            {
                "source": "narrator",
                "message": "Prepared narrative rendering from the resolved action.",
                "details": {
                    "raw_player_input": raw_player_input,
                    "expanded_player_intent": route["expanded_player_intent"],
                    "narrative_intent": action_result["outcome_summary"],
                },
            }
        )
        narrative_text = self._narrator_service.render_narrative(
            action_result=action_result,
            visible_state=visible_state,
            route_decision=route,
            output_language=session_state.get("output_language", "uk"),
            on_token=on_narration_chunk,
        )
        narrator_mentions = extract_narrator_mentions(narrative_text)
        scene_candidates = extract_available_entities(narrative_text)
        store_scene_candidates(session_state, scene_candidates)
        scene_memory_debug = apply_narrator_scene_memory(
            session_state=session_state,
            narrator_output=narrative_text,
            parsed_mentions=narrator_mentions,
            entity_resolution=entity_resolution,
            current_turn=cycle_turn,
        )
        self._entity_resolver_service.refresh_scene_entity_pool(
            session_state=session_state,
            narrative_text=narrative_text,
            resolved_entities=entity_resolution["resolved_entities"],
            time_advanced=int(action_result["time_cost"]["amount"]),
        )
        if (
            scene_candidates
            or scene_memory_debug["scene_pool_updates"]
            or scene_memory_debug["reference_pool_updates"]
            or scene_memory_debug["player_entity_mentions"]
            or scene_memory_debug["validation_warnings"]
            or scene_memory_debug["cleanup_removals"]
        ):
            decision_events.append(
                {
                    "source": "scene_memory",
                    "message": "Stored narrator-marked scene memory candidates.",
                    "details": {
                        "raw_narrator_output": scene_memory_debug["raw_narrator_output"],
                        "parsed_mentions": scene_memory_debug["parsed_mentions"],
                        "scene_entity_candidates": scene_candidates,
                        "scene_entity_mentions": scene_memory_debug["scene_entity_mentions"],
                        "reference_mentions": scene_memory_debug["reference_mentions"],
                        "player_entity_mentions": scene_memory_debug["player_entity_mentions"],
                        "scene_pool_updates": scene_memory_debug["scene_pool_updates"],
                        "reference_pool_updates": scene_memory_debug["reference_pool_updates"],
                        "cleanup_removals": scene_memory_debug["cleanup_removals"],
                        "validation_warnings": scene_memory_debug["validation_warnings"],
                    },
                }
            )

        emit_update(
            "narrator",
            {
                "narrative_text": narrative_text,
                "decision_events": list(decision_events),
            },
        )

        append_message(
            session_state,
            "player",
            raw_player_input,
            annotations=entity_resolution["annotations"],
        )
        append_message(session_state, "assistant", narrative_text)
        decision_cycle: DecisionCycle = {
            "turn": cycle_turn,
            "raw_player_input": raw_player_input,
            "events": decision_events,
        }
        append_decision_cycle(session_state, decision_cycle)

        return {
            "route": route,
            "entity_resolution": entity_resolution,
            "action_result": action_result,
            "narrative_text": narrative_text,
            "visible_state": visible_state,
            "evolution_check": evolution_check,
            "recent_messages": list(session_state["recent_messages"]),
            "decision_cycle": decision_cycle,
            "decision_history": list(session_state["decision_history"]),
        }
