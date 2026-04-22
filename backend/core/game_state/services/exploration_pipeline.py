"""End-to-end exploration-mode processing pipeline."""

from __future__ import annotations

from typing import TypedDict

from backend.core.game_state.services.consequence_service import apply_consequence_layer
from backend.core.game_state.services.session_service import (
    InMemorySessionStore,
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
        route = self._router_service.classify_player_input(raw_player_input)
        action_result = self._action_evaluation_service.evaluate_action(
            raw_player_input=raw_player_input,
            route_decision=route,
            session_state=session_state,
        )
        action_result = apply_consequence_layer(
            session_state=session_state,
            action_result=action_result,
            action_category=route["action_category"],
        )
        action_result = apply_state_updates(session_state, action_result)
        evolution_check = check_world_evolution_hook(session_state)
        visible_state = build_visible_state(session_state)
        narrative_text = self._narrator_service.render_narrative(
            action_result=action_result,
            visible_state=visible_state,
            route_decision=route,
        )

        append_message(session_state, "player", raw_player_input)
        append_message(session_state, "assistant", narrative_text)

        return {
            "route": route,
            "action_result": action_result,
            "narrative_text": narrative_text,
            "visible_state": visible_state,
            "evolution_check": evolution_check,
            "recent_messages": list(session_state["recent_messages"]),
        }

