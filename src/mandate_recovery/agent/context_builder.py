"""Build the minimal, bounded context supplied to a decision model."""

from __future__ import annotations

from typing import Any

from mandate_recovery.models import ClassificationResult, EVALUATION_FIELDS

PROMPT_VERSION = "recovery-decision-v1"


def build_context(
    transaction: dict[str, Any], classification: ClassificationResult,
    *, retry_cap: int,
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
    }
