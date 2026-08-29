"""Build the minimal, bounded context supplied to a decision model."""

from __future__ import annotations

from typing import Any

from mandate_recovery.models import ClassificationResult, EVALUATION_FIELDS

PROMPT_VERSION = "recovery-decision-v1"


def build_context(
    transaction: dict[str, Any], classification: ClassificationResult,
    *, retry_cap: int, verified_payment_id: str | None = None,
    terminal_reason: str | None = None,
) -> dict[str, Any]:
    observable = {
        key: value for key, value in transaction.items() if key not in EVALUATION_FIELDS
    }
    return {
        "prompt_version": PROMPT_VERSION,
        "transaction": observable,
        "classification": classification.to_dict(),
        "recovery_policy": {
            "retry_cap": retry_cap,
            "current_attempt": observable["attempt_number"],
            "recovery_window_expires_at": observable["recovery_window_expires_at"],
        },
        "promise_to_pay": observable.get("promise_to_pay"),
        "verified_state": {
            "payment_id": verified_payment_id,
            "terminal_reason": terminal_reason,
        },
    }
