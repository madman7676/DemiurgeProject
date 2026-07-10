"""FastAPI app for the Hyperlite exploration backend."""

from __future__ import annotations

import json
from queue import Queue
from threading import Thread
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.api.routes import (
    RouteContext,
    get_session_response,
    process_hyperlite_turn,
    process_message_response,
)
from backend.config import Settings, load_settings
from backend.core.state import InMemorySessionStore
from backend.llm.client import OllamaLLMClient
from backend.llm.narrator import Narrator


class MessageRequest(BaseModel):
    """Request payload for a single exploration-mode player message."""

    message: str
    session_state: dict[str, Any] | None = None


def create_route_context(settings: Settings) -> RouteContext:
    """Wire the backend services used by the HTTP routes."""

    session_store = InMemorySessionStore()
    llm_adapter = OllamaLLMClient(settings)
    return RouteContext(
        session_store=session_store,
        narrator=Narrator(llm_adapter),
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
        """Process a single player message through the Hyperlite pipeline."""

        request_payload = payload.model_dump(exclude_none=True)
        raw_message = request_payload["message"].strip()
        if not raw_message:
            return JSONResponse(
                status_code=400,
                content={"error": "The 'message' field is required."},
            )
        request_payload["message"] = raw_message
        return process_message_response(request_payload, app.state.route_context)

    @app.post("/api/message/stream", response_model=None)
    def post_message_stream(payload: MessageRequest):
        """Process a message and stream narrator chunks as NDJSON."""

        request_payload = payload.model_dump(exclude_none=True)
        raw_message = request_payload["message"].strip()
        if not raw_message:
            return JSONResponse(
                status_code=400,
                content={"error": "The 'message' field is required."},
            )
        request_payload["message"] = raw_message
        return StreamingResponse(
            _stream_message_response(request_payload, app.state.route_context),
            media_type="application/x-ndjson",
        )

    return app


def _stream_message_response(payload: dict[str, Any], context: RouteContext):
    """Run the sync Hyperlite pipeline in a worker while yielding narrator chunks."""

    events: Queue[str | None] = Queue()

    def emit(event: dict[str, Any]) -> None:
        events.put(json.dumps(event, ensure_ascii=False) + "\n")

    def run_pipeline() -> None:
        try:
            if "session_state" in payload and isinstance(payload["session_state"], dict):
                context.session_store.replace_session(payload["session_state"])
            result = process_hyperlite_turn(
                str(payload.get("message", "")),
                on_narration_chunk=lambda chunk: emit({"type": "narration_delta", "text": chunk}),
                context=context,
            )
            emit(
                {
                    "type": "pipeline_update",
                    "step": "hyperlite",
                    "debug": result["debug"],
                }
            )
            emit(
                {
                    "type": "final",
                    "data": {
                        "output_language": context.session_store.get_session().get("output_language", ""),
                        **result,
                    },
                }
            )
        except Exception as exc:  # pragma: no cover - defensive transport guard
            emit({"type": "error", "error": str(exc)})
        finally:
            events.put(None)

    Thread(target=run_pipeline, daemon=True).start()

    while True:
        event = events.get()
        if event is None:
            break
        yield event
