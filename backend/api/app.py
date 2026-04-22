"""Minimal FastAPI app for the exploration prototype.

Keep transport concerns here so gameplay modules remain framework-agnostic.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.api.routes import (
    RouteContext,
    get_session_response,
    process_message_response,
)
from backend.config import Settings, load_settings
from backend.core.game_state.services.exploration_pipeline import ExplorationPipeline
from backend.core.game_state.services.session_service import InMemorySessionStore
from backend.modules.action_evaluation.services.action_evaluation_service import (
    ActionEvaluationService,
)
from backend.modules.llm_connector.services.llm_client import OllamaLLMClient
from backend.modules.narrator.services.narrator_service import NarratorService
from backend.modules.router.services.router_service import RouterService


class MessageRequest(BaseModel):
    """Request payload for a single exploration-mode player message."""

    message: str
    session_state: dict[str, Any] | None = None


def create_route_context(settings: Settings) -> RouteContext:
    """Wire the backend services used by the HTTP routes."""

    session_store = InMemorySessionStore()
    llm_adapter = OllamaLLMClient(settings)
    exploration_pipeline = ExplorationPipeline(
        session_store=session_store,
        router_service=RouterService(),
        action_evaluation_service=ActionEvaluationService(llm_adapter=llm_adapter),
        narrator_service=NarratorService(llm_adapter=llm_adapter),
    )
    return RouteContext(
        session_store=session_store,
        exploration_pipeline=exploration_pipeline,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI app for the local exploration API."""

    resolved_settings = settings or load_settings()
    route_context = create_route_context(resolved_settings)

    app = FastAPI(title="Demiurge Backend", version="0.1.0")
    app.state.route_context = route_context

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        """Minimal health endpoint for local development."""

        return {"status": "ok"}

    @app.get("/api/session")
    def get_session() -> dict[str, Any]:
        """Return the current visible in-memory session state."""

        return get_session_response(app.state.route_context)

    @app.post("/api/message")
    def post_message(payload: MessageRequest) -> dict[str, Any]:
        """Process a single player message through the exploration pipeline."""

        request_payload = payload.model_dump(exclude_none=True)
        raw_message = request_payload["message"].strip()
        if not raw_message:
            return JSONResponse(
                status_code=400,
                content={"error": "The 'message' field is required."},
            )
        request_payload["message"] = raw_message
        return process_message_response(request_payload, app.state.route_context)

    return app
