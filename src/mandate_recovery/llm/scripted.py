"""Deterministic decision client for reproducible tests and batch simulation."""

from __future__ import annotations

from typing import Any

from mandate_recovery.models import AgentDecision, FailureCategory, ToolCall


class ScriptedDecisionClient:
    provider = "scripted"
    model = "deterministic-policy-v1"

    def choose_tool(
        self, context: dict[str, Any], tools: list[dict[str, Any]]
    ) -> AgentDecision:
        category = context["classification"]["predicted_category"]
        available = {tool["name"] for tool in tools}
        transaction = context["transaction"]
        choice = {
            FailureCategory.AFA_STEPUP_REQUIRED.value: ToolCall(
                "request_stepup", {
                    "mandate_id": transaction["mandate_id"],
                    "reason": "AFA is required; preserve the existing mandate.",
                },
            ),
            FailureCategory.RUPAY_HARD_BLOCK.value: ToolCall(
                "offer_alternate_method", {
                    "reason": "The same RuPay rail cannot support this recurring amount.",
                },
            ),
            FailureCategory.INSUFFICIENT_FUNDS.value: ToolCall(
                "schedule_retry", {"reason": "Funds failure is eligible for a bounded retry."},
            ),
            FailureCategory.EXPIRED_CARD.value: ToolCall(
                "schedule_retry", {
                    "reason": "Use the brief's bounded retry flow after card-update outreach.",
                },
            ),
            FailureCategory.OTHER.value: ToolCall(
                "escalate_human", {"reason": "No safe automatic root-cause action is known."},
            ),
        }[category]
        if choice.name not in available:
            # This is an explicit failure, not an invented fallback action.
            raise RuntimeError(f"scripted choice {choice.name} is not permitted")
        return AgentDecision(
            self.provider,
            self.model,
            choice.arguments["reason"],
            (choice,),
        )
