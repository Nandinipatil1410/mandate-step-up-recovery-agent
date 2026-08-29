"""Explicit, code-enforced retry stopping rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StoppingDecision:
    should_stop: bool
    reason_code: str | None
    explanation: str


def evaluate_stopping_rules(
    *, attempt_number: int, retry_cap: int, now: datetime,
    recovery_window_expires_at: datetime,
) -> StoppingDecision:
    if attempt_number >= retry_cap:
        return StoppingDecision(True, "RETRY_CAP_REACHED", "Maximum debit attempts reached.")
    if now >= recovery_window_expires_at:
        return StoppingDecision(True, "RECOVERY_WINDOW_EXPIRED", "Recovery window has expired.")
    return StoppingDecision(False, None, "Another bounded attempt may be scheduled.")
