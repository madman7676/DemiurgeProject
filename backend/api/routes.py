"""Route-facing handlers for the minimal exploration API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.core.game_state.services.exploration_pipeline import ExplorationPipeline
from backend.core.game_state.services.session_service import (
    InMemorySessionStore,
    build_visible_state,
)


@dataclass
class RouteContext:
    """Services required by the API route handlers."""

    session_store: InMemorySessionStore
    exploration_pipeline: ExplorationPipeline


def get_session_response(context: RouteContext) -> dict[str, Any]:
    """Return the current visible in-memory session state."""

    session_state = context.session_store.get_session()
    return {
        "session_id": session_state["session_id"],
        "visible_state": build_visible_state(session_state),
        "recent_messages": list(session_state["recent_messages"]),
    }


def process_message_response(
    payload: dict[str, Any],
    context: RouteContext,
) -> dict[str, Any]:
    """Process a single player message through the exploration pipeline."""

    raw_message = str(payload.get("message", "")).strip()

    if "session_state" in payload and isinstance(payload["session_state"], dict):
        context.session_store.replace_session(payload["session_state"])

    pipeline_result = context.exploration_pipeline.process_player_message(raw_message)
    return {
        "session_id": context.session_store.get_session()["session_id"],
        "route": pipeline_result["route"],
        "result": pipeline_result["action_result"],
        "narrative_text": pipeline_result["narrative_text"],
        "visible_state": pipeline_result["visible_state"],
        "evolution_check": pipeline_result["evolution_check"],
        "recent_messages": pipeline_result["recent_messages"],
    }
