"""Hard-enforced execution of the fixed recovery tool set."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mandate_recovery.models import FailureCategory, ToolCall, ToolResult, parse_iso_datetime

from .specs import TOOL_SPECS


@dataclass(frozen=True)
class ToolExecutionContext:
    transaction: dict[str, Any]
    classified_category: str
    now: datetime
    retry_cap: int
    verified_payment_id: str | None = None
    terminal_reason: str | None = None


class ToolValidationError(ValueError):
    """Raised before execution when a call violates its JSON-like contract."""


def validate_call(call: ToolCall) -> None:
    spec = TOOL_SPECS.get(call.name)
    if spec is None:
        raise ToolValidationError(f"unknown tool: {call.name}")
    schema = spec["parameters"]
    required = set(schema["required"])
    supplied = set(call.arguments)
    if missing := required - supplied:
        raise ToolValidationError(f"missing arguments for {call.name}: {sorted(missing)}")
    if extra := supplied - set(schema["properties"]):
        raise ToolValidationError(f"unexpected arguments for {call.name}: {sorted(extra)}")
    for name, value in call.arguments.items():
        if schema["properties"][name]["type"] == "string" and (
            not isinstance(value, str) or not value.strip()
        ):
            raise ToolValidationError(f"{call.name}.{name} must be a non-empty string")


def execute_tool(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
    """Execute only bounded simulated effects; no money or messages leave the app."""
    validate_call(call)
    transaction = context.transaction
    category = context.classified_category

    if call.name == "request_stepup":
        if category != FailureCategory.AFA_STEPUP_REQUIRED.value:
            return _reject(call.name, "CATEGORY_NOT_ELIGIBLE")
        if call.arguments["mandate_id"] != transaction["mandate_id"]:
            return _reject(call.name, "MANDATE_ID_MISMATCH")
        return ToolResult(call.name, True, "approval_requested", "SAME_MANDATE_STEPUP", {
            "mandate_id": transaction["mandate_id"], "created_new_mandate": False,
        })

    if call.name == "offer_alternate_method":
        if category != FailureCategory.RUPAY_HARD_BLOCK.value:
            return _reject(call.name, "CATEGORY_NOT_ELIGIBLE")
        return ToolResult(call.name, True, "alternate_method_offered", "RUPAY_SAME_RAIL_BLOCKED", {
            "same_rail_retry": False, "offered_methods": ["upi", "different_card"],
        })

    if call.name == "schedule_retry":
        if transaction.get("retry_owner") == "razorpay":
            return _reject(call.name, "EXTERNAL_RETRY_ALREADY_SCHEDULED", {
                "retry_owner": "razorpay",
                "gateway_retry_at": transaction.get("gateway_retry_at"),
            })
        if category == FailureCategory.RUPAY_HARD_BLOCK.value:
            return _reject(call.name, "RUPAY_RETRY_FORBIDDEN")
        attempt_number = int(transaction["attempt_number"])
        if attempt_number >= context.retry_cap:
            return _reject(call.name, "RETRY_CAP_REACHED", {"attempt_number": attempt_number})
        if context.now >= parse_iso_datetime(transaction["recovery_window_expires_at"]):
            return _reject(call.name, "RECOVERY_WINDOW_EXPIRED")
        return ToolResult(call.name, True, "retry_accepted", "BOUNDED_RETRY_ALLOWED", {
            "current_attempt": attempt_number, "next_attempt": attempt_number + 1,
        })

    if call.name == "send_notification":
        return ToolResult(call.name, True, "notification_draft_requested", "DRAFT_ONLY", {
            "message_purpose": call.arguments["message_purpose"],
            "contacted_customer": False,
            "retry_owner": transaction.get("retry_owner"),
            "gateway_retry_at": transaction.get("gateway_retry_at"),
        })

    if call.name == "escalate_human":
        return ToolResult(call.name, True, "escalated", "HUMAN_REVIEW_REQUIRED", {
            "reason": call.arguments["reason"],
        })

    if call.name == "mark_recovered":
        if not context.verified_payment_id:
            return _reject(call.name, "PAYMENT_EVIDENCE_REQUIRED")
        if call.arguments["payment_id"] != context.verified_payment_id:
            return _reject(call.name, "PAYMENT_EVIDENCE_MISMATCH")
        return ToolResult(call.name, True, "recovered", "VERIFIED_PAYMENT", {
            "payment_id": context.verified_payment_id,
        })

    if call.name == "mark_unrecoverable":
        if not context.terminal_reason:
            return _reject(call.name, "TERMINAL_CONDITION_REQUIRED")
        return ToolResult(call.name, True, "unrecoverable", context.terminal_reason, {
            "reason": call.arguments["reason"],
        })

    raise ToolValidationError(f"unimplemented tool: {call.name}")


def _reject(name: str, reason: str, details: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(name, False, "rejected", reason, details or {})
