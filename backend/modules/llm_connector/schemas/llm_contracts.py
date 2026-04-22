"""Contracts for LLM requests and adapter responses."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class LLMGenerateRequest(TypedDict):
    """Minimal request shape for text generation."""

    system_prompt: str
    user_prompt: str


class LLMGenerateResponse(TypedDict):
    """Adapter response used by gameplay-facing services."""

    text: str
    provider: str
    model: str
    used_mock: bool
    error: NotRequired[str]
