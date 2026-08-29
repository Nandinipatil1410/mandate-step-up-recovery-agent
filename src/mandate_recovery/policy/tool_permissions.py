"""Dynamically restrict tools by classified cause and verified state."""

from __future__ import annotations

from mandate_recovery.models import FailureCategory


INITIAL_TOOL_PERMISSIONS: dict[str, tuple[str, ...]] = {
    FailureCategory.AFA_STEPUP_REQUIRED.value: (
        "request_stepup", "send_notification", "escalate_human",
    ),
    # The brief explicitly permits only this intervention for the hard block.
    FailureCategory.RUPAY_HARD_BLOCK.value: ("offer_alternate_method",),
    FailureCategory.INSUFFICIENT_FUNDS.value: (
        "schedule_retry", "send_notification", "escalate_human",
    ),
    FailureCategory.EXPIRED_CARD.value: (
        "schedule_retry", "send_notification", "escalate_human",
    ),
    FailureCategory.OTHER.value: ("escalate_human",),
}


def permitted_tools(category: str, *, verified_payment_id: str | None = None,
                    terminal_reason: str | None = None) -> tuple[str, ...]:
    if category not in INITIAL_TOOL_PERMISSIONS:
        raise ValueError(f"unsupported failure category: {category}")
    if verified_payment_id and terminal_reason:
        raise ValueError("state cannot be both recovered and terminally unrecoverable")
    if verified_payment_id:
        return ("mark_recovered",)
    if terminal_reason:
        return ("mark_unrecoverable",)
    return INITIAL_TOOL_PERMISSIONS[category]
