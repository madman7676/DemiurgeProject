"""Coordinates which backend modules should process a player action."""

from __future__ import annotations

import logging

from backend.modules.router.schemas.router_contracts import RouteDecision


logger = logging.getLogger(__name__)


class RouterService:
    """Map raw player input to a minimal exploration-oriented action category."""

    def classify_player_input(self, raw_player_input: str) -> RouteDecision:
        """Classify input using lightweight heuristics for the first playable loop."""

        lowered = raw_player_input.lower()
        logger.info("Routing raw player input: %s", raw_player_input)

        if any(keyword in lowered for keyword in ["attack", "fight", "kill", "stab", "shoot"]):
            action_category = "combat_attempt"
            reasoning = "Input indicates combat intent, which is not available in exploration mode."
        elif lowered.endswith("?") or any(
            lowered.startswith(prefix)
            for prefix in ["what ", "who ", "where ", "when ", "why ", "how "]
        ):
            action_category = "question"
            reasoning = "Input is phrased as a question or meta inquiry."
        elif any(keyword in lowered for keyword in ["go ", "walk", "move", "travel", "head to", "north", "south", "east", "west"]):
            action_category = "movement"
            reasoning = "Input focuses on repositioning or travel."
        elif any(keyword in lowered for keyword in ["say", "speak", "talk", "hello", "greet"]):
            action_category = "speech"
            reasoning = "Input focuses on speaking or greeting."
        elif any(keyword in lowered for keyword in ["look", "inspect", "examine", "search", "observe"]):
            action_category = "inspection"
            reasoning = "Input focuses on observing the surroundings."
        elif any(keyword in lowered for keyword in ["wait", "rest", "pause", "hesitate", "think"]):
            action_category = "idle"
            reasoning = "Input implies deliberate delay or low-intensity action."
        elif "ask" in lowered:
            action_category = "question"
            reasoning = "Input centers on asking for information."
        else:
            action_category = "inspection"
            reasoning = "Input suggests a general exploratory action."

        return {
            "action_category": action_category,
            "target_modules": [
                "router",
                "action_evaluation",
                "world_evolution",
                "narrator",
            ],
            "reasoning": reasoning,
        }
