"""Provider-neutral decision-client contract."""

from __future__ import annotations

from typing import Any, Protocol

from mandate_recovery.models import AgentDecision


class DecisionClient(Protocol):
    provider: str
    model: str

    def choose_tool(
        self, context: dict[str, Any], tools: list[dict[str, Any]]
    ) -> AgentDecision: ...


class LLMProviderError(RuntimeError):
    """Provider was unavailable or returned an unusable response."""
