"""Promise-to-pay state with a strict single-follow-up policy."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from mandate_recovery.models import parse_iso_datetime


@dataclass(frozen=True)
class PromiseState:
    status: str
    promised_payment_at: datetime
    follow_up_count: int = 0


@dataclass(frozen=True)
class PromiseDecision:
    action: str
    reason_code: str


class PromiseTracker:
    def from_record(self, value: dict | None) -> PromiseState | None:
        if value is None:
            return None
        state = PromiseState(
            status=str(value["status"]),
            promised_payment_at=parse_iso_datetime(str(value["promised_payment_at"])),
            follow_up_count=int(value["follow_up_count"]),
        )
        if state.status not in {"active", "missed"}:
            raise ValueError("unsupported promise status")
        if not 0 <= state.follow_up_count <= 1:
            raise ValueError("promise follow_up_count must be zero or one")
        return state

    def evaluate(self, state: PromiseState, *, now: datetime) -> PromiseDecision:
        if state.status == "active" and now < state.promised_payment_at:
            return PromiseDecision("wait", "PROMISE_NOT_DUE")
        if state.follow_up_count == 0:
            return PromiseDecision("follow_up", "MISSED_PROMISE_FIRST_FOLLOW_UP")
        return PromiseDecision("stop_follow_up", "PROMISE_FOLLOW_UP_LIMIT_REACHED")

    def record_follow_up(self, state: PromiseState) -> PromiseState:
        if state.follow_up_count >= 1:
            raise ValueError("only one promise follow-up is allowed")
        return replace(state, status="missed", follow_up_count=1)
