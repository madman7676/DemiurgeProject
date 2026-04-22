"""End-to-end exploration-mode processing pipeline."""

from __future__ import annotations

from typing import TypedDict

from backend.core.game_state.contracts import DecisionCycle, DecisionEvent
from backend.core.game_state.services.consequence_service import apply_consequence_layer
from backend.core.game_state.services.session_service import (
    InMemorySessionStore,
    append_decision_cycle,
    append_message,
    build_visible_state,
)
from backend.core.game_state.services.state_update_service import apply_state_updates
from backend.modules.action_evaluation.schemas.action_evaluation_contracts import (
    ActionProcessingContract,
)
from backend.modules.action_evaluation.services.action_evaluation_service import (
    ActionEvaluationService,
)
from backend.modules.narrator.services.narrator_service import NarratorService
from backend.modules.router.schemas.router_contracts import RouteDecision
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
        action_evaluation_service: ActionEvaluationService,
        narrator_service: NarratorService,
    ) -> None:
        self._session_store = session_store
        self._router_service = router_service
        self._action_evaluation_service = action_evaluation_service
        self._narrator_service = narrator_service

    def process_player_message(self, raw_player_input: str) -> ExplorationPipelineResult:
        """Process one exploration action from input to visible frontend result."""

        session_state = self._session_store.get_session()
        cycle_turn = session_state["turn_count"] + 1
        decision_events: list[DecisionEvent] = []

        route = self._router_service.classify_player_input(raw_player_input)
        decision_events.append(
            {
                "source": "router",
                "message": f"Classified input as {route['action_category']}.",
                "details": {
                    "category": route["action_category"],
                    "reasoning": route["reasoning"],
                },
            }
        )
        action_result = self._action_evaluation_service.evaluate_action(
            raw_player_input=raw_player_input,
            route_decision=route,
            session_state=session_state,
        )
        decision_events.append(
            {
                "source": "action_evaluation",
                "message": "Interpreted player intent and assigned feasibility.",
                "details": {
                    "primary_goal": action_result["interpreted_intent"]["primary_goal"],
                    "approach": action_result["interpreted_intent"]["approach"],
                    "feasibility_score": action_result["feasibility_score"],
                },
            }
        )
        decision_events.append(
            {
                "source": "time_cost",
                "message": "Assigned in-world time cost.",
                "details": {
                    "amount": action_result["time_cost"]["amount"],
                    "unit": action_result["time_cost"]["unit"],
                },
            }
        )
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
        visible_state = build_visible_state(session_state)
        decision_events.append(
            {
                "source": "narrator",
                "message": "Prepared narrative rendering from the resolved action.",
                "details": {
                    "raw_player_input": raw_player_input,
                    "narrative_intent": action_result["outcome_summary"],
                },
            }
        )
        narrative_text = self._narrator_service.render_narrative(
            action_result=action_result,
            visible_state=visible_state,
            route_decision=route,
        )

        append_message(session_state, "player", raw_player_input)
        append_message(session_state, "assistant", narrative_text)
        decision_cycle: DecisionCycle = {
            "turn": cycle_turn,
            "raw_player_input": raw_player_input,
            "events": decision_events,
        }
        append_decision_cycle(session_state, decision_cycle)

        return {
            "route": route,
            "action_result": action_result,
            "narrative_text": narrative_text,
            "visible_state": visible_state,
            "evolution_check": evolution_check,
            "recent_messages": list(session_state["recent_messages"]),
            "decision_cycle": decision_cycle,
            "decision_history": list(session_state["decision_history"]),
        }
