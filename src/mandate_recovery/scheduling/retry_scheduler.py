"""Deterministic retry scheduling with notice and window enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .stopping_rules import evaluate_stopping_rules


@dataclass(frozen=True)
class RetrySchedule:
    accepted: bool
    reason_code: str
    current_attempt: int
    next_attempt: int | None
    notice_at: datetime | None
    retry_at: datetime | None


class RetryScheduler:
    def __init__(self, *, retry_cap: int, backoff_hours: tuple[int, ...],
                 pre_debit_notice_hours: int) -> None:
        self.retry_cap = retry_cap
        self.backoff_hours = backoff_hours
        self.pre_debit_notice_hours = pre_debit_notice_hours

    def schedule(
        self, *, attempt_number: int, now: datetime,
        recovery_window_expires_at: datetime,
    ) -> RetrySchedule:
        stop = evaluate_stopping_rules(
            attempt_number=attempt_number, retry_cap=self.retry_cap, now=now,
            recovery_window_expires_at=recovery_window_expires_at,
        )
        if stop.should_stop:
            return RetrySchedule(False, str(stop.reason_code), attempt_number, None, None, None)
        backoff = timedelta(hours=self.backoff_hours[attempt_number - 1])
        retry_at = now + backoff
        if retry_at > recovery_window_expires_at:
            return RetrySchedule(
                False, "NEXT_RETRY_OUTSIDE_WINDOW", attempt_number, None, None, None
            )
        notice_at = retry_at - timedelta(hours=self.pre_debit_notice_hours)
        return RetrySchedule(
            True, "RETRY_SCHEDULED", attempt_number, attempt_number + 1,
            max(now, notice_at), retry_at,
        )
