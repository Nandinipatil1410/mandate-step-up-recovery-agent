"""Compliant agent flow and intentionally naive comparison baseline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mandate_recovery.agent import AgentTurn, RecoveryAgent
from mandate_recovery.models import ClassificationResult, FailureCategory


@dataclass(frozen=True)
class FlowAction:
    name: str
    accepted: bool
    reason_code: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "accepted": self.accepted,
            "reason_code": self.reason_code, "details": self.details,
        }


def run_compliant_action(
    agent: RecoveryAgent, transaction: dict[str, Any],
    classification: ClassificationResult, *, now: datetime,
) -> tuple[FlowAction, AgentTurn]:
    turn = agent.decide_and_execute(transaction, classification, now=now)
    result = turn.tool_result
    return FlowAction(
        result.tool_name, result.accepted, result.reason_code, result.details
    ), turn


def run_naive_action(
    transaction: dict[str, Any], classification: ClassificationResult,
    *, retry_cap: int,
) -> FlowAction:
    """Simulate the broken baseline; it never enters the bounded tool registry."""
    category = classification.predicted_category
    if category == FailureCategory.AFA_STEPUP_REQUIRED.value:
        return FlowAction("spawn_new_mandate", True, "BROKEN_NEW_MANDATE_FLOW", {
            "original_mandate_id": transaction["mandate_id"],
            "created_new_mandate": True,
        })
    if category == FailureCategory.RUPAY_HARD_BLOCK.value:
        return FlowAction("retry_same_rail", True, "NAIVE_RUPAY_RETRY", {
            "same_rail_retry": True,
        })
    if category in {
        FailureCategory.INSUFFICIENT_FUNDS.value,
        FailureCategory.EXPIRED_CARD.value,
    }:
        if int(transaction["attempt_number"]) >= retry_cap:
            return FlowAction("schedule_retry", False, "RETRY_CAP_REACHED", {})
        return FlowAction("schedule_retry", True, "BASELINE_RETRY", {})
    return FlowAction("escalate_human", True, "BASELINE_ESCALATION", {})
