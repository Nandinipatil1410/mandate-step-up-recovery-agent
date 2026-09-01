"""One-turn bounded recovery agent: reason, select, validate, execute, trace."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from mandate_recovery.llm import DecisionClient
from mandate_recovery.models import AgentDecision, ClassificationResult, ToolResult
from mandate_recovery.policy import permitted_tools
from mandate_recovery.tools import ToolExecutionContext, execute_tool, tool_specs

from .context_builder import build_context


class AgentDecisionError(ValueError):
    """The model response did not satisfy the bounded decision contract."""


@dataclass(frozen=True)
class AgentTurn:
    context: dict[str, Any]
    permitted_tools: tuple[str, ...]
    decision: AgentDecision
    policy_validation: str
    tool_result: ToolResult

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RecoveryAgent:
    def __init__(self, client: DecisionClient, *, retry_cap: int) -> None:
        self.client = client
        self.retry_cap = retry_cap

    def decide_and_execute(
        self, transaction: dict[str, Any], classification: ClassificationResult,
        *, now: datetime, verified_payment_id: str | None = None,
        terminal_reason: str | None = None,
    ) -> AgentTurn:
        context = build_context(
            transaction, classification, retry_cap=self.retry_cap,
            verified_payment_id=verified_payment_id, terminal_reason=terminal_reason,
        )
        allowed = permitted_tools(
            classification.predicted_category,
            verified_payment_id=verified_payment_id,
            terminal_reason=terminal_reason,
            retry_owner=transaction.get("retry_owner"),
        )
        decision = self.client.choose_tool(context, tool_specs(allowed))
        if len(decision.tool_calls) != 1:
            raise AgentDecisionError(
                f"agent must choose exactly one tool; received {len(decision.tool_calls)}"
            )
        call = decision.tool_calls[0]
        if call.name not in allowed:
            raise AgentDecisionError(f"tool {call.name} was not permitted for this state")
        result = execute_tool(call, ToolExecutionContext(
            transaction=transaction,
            classified_category=classification.predicted_category,
            now=now,
            retry_cap=self.retry_cap,
            verified_payment_id=verified_payment_id,
            terminal_reason=terminal_reason,
        ))
        return AgentTurn(context, allowed, decision, "TOOL_WAS_PERMITTED", result)
