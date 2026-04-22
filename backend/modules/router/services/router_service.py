"""Coordinates which backend modules should process a player action."""

from __future__ import annotations

from backend.modules.router.schemas.router_contracts import RouteDecision


class RouterService:
    """Map raw player input to a minimal exploration-oriented action category."""

    def classify_player_input(self, raw_player_input: str) -> RouteDecision:
        """Classify input using lightweight heuristics for the first playable loop."""

        lowered = raw_player_input.lower()

        if any(keyword in lowered for keyword in ["attack", "fight", "kill", "stab", "shoot"]):
            action_category = "combat_attempt"
            reasoning = "Input indicates combat intent, which is not available in exploration mode."
        elif any(keyword in lowered for keyword in ["go ", "walk", "move", "travel", "head to"]):
            action_category = "move"
            reasoning = "Input focuses on repositioning or travel."
        elif any(keyword in lowered for keyword in ["ask", "tell", "say", "speak", "talk", "hello"]):
            action_category = "talk"
            reasoning = "Input focuses on speech or interaction with a character."
        elif any(keyword in lowered for keyword in ["look", "inspect", "examine", "search", "observe"]):
            action_category = "observe"
            reasoning = "Input focuses on gathering information from the environment."
        elif any(keyword in lowered for keyword in ["wait", "rest", "pause", "hesitate", "think"]):
            action_category = "wait"
            reasoning = "Input implies deliberate delay or low-intensity action."
        else:
            action_category = "interact"
            reasoning = "Input suggests a general exploratory interaction."

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
