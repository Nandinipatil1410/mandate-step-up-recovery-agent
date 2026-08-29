"""Full checkpoint-4 lifecycle using simulated time and append-only audit events."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from mandate_recovery.agent import AgentTurn, RecoveryAgent
from mandate_recovery.audit import AuditTrail
from mandate_recovery.classification import classify
from mandate_recovery.classification.rules import ClassificationConfig
from mandate_recovery.models import EVALUATION_FIELDS, FailureCategory, parse_iso_datetime
from mandate_recovery.notifications import NotificationDraft, NotificationGenerator
from mandate_recovery.promises import PromiseTracker
from mandate_recovery.scheduling import RetryScheduler, SimulatedClock

from .config import RecoveryConfig
from .flows import run_compliant_action
from .outcome_simulator import simulate_outcome


@dataclass(frozen=True)
class LifecycleResult:
    transaction_id: str
    category: str
    final_state: str
    recovered: bool
    recovered_amount_paise: int
    final_attempt_number: int
    unresolved_reason: str | None
    time_to_recovery_hours: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RecoveryLifecycleRunner:
    def __init__(
        self, *, agent: RecoveryAgent, notification_generator: NotificationGenerator,
        recovery_config: RecoveryConfig, classification_config: ClassificationConfig,
        audit_trail: AuditTrail, seed: int,
    ) -> None:
        self.agent = agent
        self.notifications = notification_generator
        self.config = recovery_config
        self.classification_config = classification_config
        self.audit = audit_trail
        self.seed = seed
        self.notification_drafts: list[dict[str, Any]] = []
        self.promise_tracker = PromiseTracker()
        self.scheduler = RetryScheduler(
            retry_cap=recovery_config.retry_cap,
            backoff_hours=recovery_config.retry_backoff_hours,
            pre_debit_notice_hours=recovery_config.pre_debit_notice_hours,
        )

    def run(self, source: dict[str, Any]) -> LifecycleResult:
        transaction = {
            key: value for key, value in source.items() if key not in EVALUATION_FIELDS
        }
        transaction_id = str(transaction["transaction_id"])
        started_at = parse_iso_datetime(transaction["timestamp"])
        clock = SimulatedClock(started_at)
        classification = classify(transaction, config=self.classification_config)
        state = "classified"
        self.audit.append(
            transaction_id=transaction_id, event_type="classification", actor="rule_engine",
            reason_code=classification.rule_id, timestamp=clock.now(),
            previous_state="failed", new_state=state,
            metadata=classification.to_dict(),
        )

        state = self._handle_promise(transaction, clock, state)
        action, turn = run_compliant_action(
            self.agent, transaction, classification, now=clock.now()
        )
        state = self._record_agent_turn(transaction_id, turn, clock.now(), state)

        category = classification.predicted_category
        if category in {
            FailureCategory.AFA_STEPUP_REQUIRED.value,
            FailureCategory.RUPAY_HARD_BLOCK.value,
        }:
            purpose = (
                "stepup" if category == FailureCategory.AFA_STEPUP_REQUIRED.value
                else "alternate_method"
            )
            self._notify(
                transaction, purpose, action.reason_code, clock.now(), state
            )
            outcome = simulate_outcome(
                transaction, category, self.config.compliant_success_probability,
                seed=self.seed, action_accepted=action.accepted,
            )
            if outcome.recovered:
                state = self._mark_recovered(
                    transaction, classification, clock, state,
                    payment_id=f"pay_sim_{transaction_id}",
                )
                return self._result(transaction, category, state, True, None, started_at, clock.now())
            previous = state
            state = "escalated"
            reason = "CUSTOMER_APPROVAL_NOT_COMPLETED"
            self.audit.append(
                transaction_id=transaction_id, event_type="escalation", actor="lifecycle",
                reason_code=reason, timestamp=clock.now(), previous_state=previous,
                new_state=state, metadata={"action": action.to_dict()},
            )
            self._notify(transaction, "escalation", reason, clock.now(), state)
            return self._result(transaction, category, state, False, reason, started_at, clock.now())

        if category == FailureCategory.OTHER.value:
            self._notify(transaction, "escalation", action.reason_code, clock.now(), state)
            return self._result(
                transaction, category, "escalated", False, action.reason_code,
                started_at, clock.now(),
            )

        return self._run_retry_lifecycle(
            transaction, classification, clock, state, started_at
        )

    def _handle_promise(
        self, transaction: dict[str, Any], clock: SimulatedClock, state: str
    ) -> str:
        promise = self.promise_tracker.from_record(transaction.get("promise_to_pay"))
        if promise is None:
            return state
        decision = self.promise_tracker.evaluate(promise, now=clock.now())
        if decision.action == "wait":
            previous = state
            state = "waiting_for_promise"
            self.audit.append(
                transaction_id=transaction["transaction_id"], event_type="promise_wait",
                actor="promise_tracker", reason_code=decision.reason_code,
                timestamp=clock.now(), previous_state=previous, new_state=state,
                metadata={"promised_payment_at": promise.promised_payment_at.isoformat()},
            )
            clock.advance_to(promise.promised_payment_at)
            decision = self.promise_tracker.evaluate(promise, now=clock.now())
        if decision.action == "follow_up":
            updated = self.promise_tracker.record_follow_up(promise)
            previous = state
            state = "promise_followed_up"
            self.audit.append(
                transaction_id=transaction["transaction_id"], event_type="promise_follow_up",
                actor="promise_tracker", reason_code=decision.reason_code,
                timestamp=clock.now(), previous_state=previous, new_state=state,
                metadata={"follow_up_count": updated.follow_up_count},
            )
            self._notify(
                transaction, "promise_follow_up", decision.reason_code, clock.now(), state
            )
        elif decision.action == "stop_follow_up":
            self.audit.append(
                transaction_id=transaction["transaction_id"], event_type="promise_stop",
                actor="promise_tracker", reason_code=decision.reason_code,
                timestamp=clock.now(), previous_state=state, new_state=state,
                metadata={"follow_up_count": promise.follow_up_count},
            )
        return state

    def _run_retry_lifecycle(
        self, transaction: dict[str, Any], classification, clock: SimulatedClock,
        state: str, started_at: datetime,
    ) -> LifecycleResult:
        category = classification.predicted_category
        window_end = parse_iso_datetime(transaction["recovery_window_expires_at"])
        current_attempt = int(transaction["attempt_number"])
        while True:
            schedule = self.scheduler.schedule(
                attempt_number=current_attempt, now=clock.now(),
                recovery_window_expires_at=window_end,
            )
            if not schedule.accepted:
                transaction["attempt_number"] = current_attempt
                state = self._mark_unrecoverable(
                    transaction, classification, clock, state, schedule.reason_code
                )
                return self._result(
                    transaction, category, state, False, schedule.reason_code,
                    started_at, clock.now(),
                )
            previous = state
            state = "retry_scheduled"
            self.audit.append(
                transaction_id=transaction["transaction_id"], event_type="retry_scheduled",
                actor="retry_scheduler", reason_code=schedule.reason_code,
                timestamp=clock.now(), previous_state=previous, new_state=state,
                metadata={
                    "current_attempt": current_attempt,
                    "next_attempt": schedule.next_attempt,
                    "notice_at": schedule.notice_at.isoformat(),
                    "retry_at": schedule.retry_at.isoformat(),
                },
            )
            clock.advance_to(schedule.notice_at)
            self._notify(transaction, "retry_notice", schedule.reason_code, clock.now(), state)
            clock.advance_to(schedule.retry_at)
            next_attempt = int(schedule.next_attempt)
            recovered = self._retry_succeeds(
                transaction["transaction_id"], next_attempt,
                self.config.compliant_success_probability[category],
            )
            previous = state
            state = "retry_succeeded" if recovered else "retry_failed"
            self.audit.append(
                transaction_id=transaction["transaction_id"], event_type="retry_executed",
                actor="retry_scheduler",
                reason_code="PAYMENT_CAPTURED" if recovered else "PAYMENT_FAILED",
                timestamp=clock.now(), previous_state=previous, new_state=state,
                metadata={"attempt_number": next_attempt, "recovered": recovered},
            )
            transaction["attempt_number"] = next_attempt
            if recovered:
                state = self._mark_recovered(
                    transaction, classification, clock, state,
                    payment_id=f"pay_sim_{transaction['transaction_id']}_{next_attempt}",
                )
                return self._result(
                    transaction, category, state, True, None, started_at, clock.now()
                )
            current_attempt = next_attempt

    def _retry_succeeds(self, transaction_id: str, attempt: int, probability: float) -> bool:
        digest = hashlib.sha256(
            f"{self.seed}:{transaction_id}:retry:{attempt}".encode("utf-8")
        ).digest()
        return int.from_bytes(digest[:8], "big") / 2**64 < probability

    def _mark_recovered(
        self, transaction, classification, clock, state, *, payment_id: str
    ) -> str:
        turn = self.agent.decide_and_execute(
            transaction, classification, now=clock.now(), verified_payment_id=payment_id
        )
        return self._record_agent_turn(
            transaction["transaction_id"], turn, clock.now(), state
        )

    def _mark_unrecoverable(
        self, transaction, classification, clock, state, reason: str
    ) -> str:
        turn = self.agent.decide_and_execute(
            transaction, classification, now=clock.now(), terminal_reason=reason
        )
        return self._record_agent_turn(
            transaction["transaction_id"], turn, clock.now(), state
        )

    def _record_agent_turn(
        self, transaction_id: str, turn: AgentTurn, timestamp: datetime, state: str
    ) -> str:
        self.audit.append(
            transaction_id=transaction_id, event_type="agent_decision", actor="recovery_agent",
            reason_code="TOOL_SELECTED", timestamp=timestamp,
            previous_state=state, new_state=state,
            metadata={
                "provider": turn.decision.provider, "model": turn.decision.model,
                "rationale": turn.decision.rationale,
                "permitted_tools": list(turn.permitted_tools),
                "tool_call": turn.decision.tool_calls[0].__dict__,
                "policy_validation": turn.policy_validation,
            },
        )
        result = turn.tool_result
        new_state = result.status
        self.audit.append(
            transaction_id=transaction_id, event_type="tool_execution", actor="bounded_tool",
            reason_code=result.reason_code, timestamp=timestamp,
            previous_state=state, new_state=new_state, metadata=result.to_dict(),
        )
        return new_state

    def _notify(
        self, transaction: dict[str, Any], purpose: str, reason: str,
        timestamp: datetime, state: str,
    ) -> NotificationDraft:
        draft = self.notifications.generate(
            purpose=purpose, transaction_id=transaction["transaction_id"],
            amount_paise=transaction["amount_paise"], context_reason=reason,
        )
        row = {
            "transaction_id": transaction["transaction_id"],
            "created_at": timestamp.isoformat(), **draft.to_dict(),
        }
        self.notification_drafts.append(row)
        self.audit.append(
            transaction_id=transaction["transaction_id"], event_type="notification_drafted",
            actor="notification_generator", reason_code=purpose.upper(),
            timestamp=timestamp, previous_state=state, new_state=state,
            metadata=draft.to_dict(),
        )
        return draft

    def _result(
        self, transaction, category, state, recovered, unresolved_reason,
        started_at, ended_at,
    ) -> LifecycleResult:
        return LifecycleResult(
            transaction_id=transaction["transaction_id"], category=category,
            final_state=state, recovered=recovered,
            recovered_amount_paise=transaction["amount_paise"] if recovered else 0,
            final_attempt_number=int(transaction["attempt_number"]),
            unresolved_reason=unresolved_reason,
            time_to_recovery_hours=(
                round((ended_at - started_at).total_seconds() / 3600, 2)
                if recovered else None
            ),
        )
