"""Conservative adapter from verified Razorpay events to the bounded agent."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from mandate_recovery.agent import AgentDecisionError, RecoveryAgent
from mandate_recovery.audit import AuditTrail
from mandate_recovery.classification import classify
from mandate_recovery.llm import (
    DecisionClient, GroqDecisionClient, LLMProviderError, ScriptedDecisionClient,
)
from mandate_recovery.models import ClassificationResult, FailureCategory
from mandate_recovery.recovery import load_recovery_config


@dataclass(frozen=True)
class LiveRecoveryResult:
    processing_status: str
    event: str
    classification: dict[str, Any] | None
    decision: dict[str, Any] | None
    tool_result: dict[str, Any] | None
    safety_notes: tuple[str, ...]
    audit_chain_valid: bool
    audit_events: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def configured_live_decision_provider() -> str:
    """Resolve the live provider without exposing or persisting credentials."""
    requested = os.environ.get("LIVE_DECISION_PROVIDER", "auto").strip().lower()
    if requested not in {"auto", "groq", "scripted"}:
        raise ValueError(
            "LIVE_DECISION_PROVIDER must be one of: auto, groq, scripted"
        )
    if requested == "scripted":
        return "scripted"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    return "scripted"


def _decision_client() -> DecisionClient:
    provider = configured_live_decision_provider()
    if provider == "scripted":
        return ScriptedDecisionClient()
    config = load_recovery_config()
    return GroqDecisionClient(
        model=config.groq_model,
        base_url=config.groq_base_url,
        timeout_seconds=config.groq_timeout_seconds,
    )


def _positive_int(value: Any, fallback: int = 1) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return fallback


def _classification(
    normalized: dict[str, Any], transaction: dict[str, Any]
) -> ClassificationResult:
    method = str(normalized.get("payment_method") or "unknown").lower()
    if method not in {"card", "upi"} or (
        method == "card" and not transaction.get("card_network")
    ):
        return ClassificationResult(
            FailureCategory.OTHER.value,
            "LIVE_UNSUPPORTED_PAYMENT_METHOD",
            "The signed webhook does not contain supported root-cause evidence for this payment method.",
            {
                "payment_method": method,
                "error_code": normalized.get("error_code"),
                "error_reason": normalized.get("error_reason"),
                "error_source": normalized.get("error_source"),
                "error_step": normalized.get("error_step"),
            },
        )
    return classify(transaction)


def _transaction(
    normalized: dict[str, Any], event_id: str, now: datetime
) -> dict[str, Any]:
    amount = _positive_int(normalized.get("amount_paise"))
    method = str(normalized.get("payment_method") or "unknown").lower()
    payment_rail = method if method in {"card", "upi"} else "upi"
    network = normalized.get("card_network") if payment_rail == "card" else None
    return {
        # The model receives stable role labels, not Razorpay customer, payment,
        # or subscription identifiers. Verified identifiers remain server-side.
        "transaction_id": f"live_{event_id}",
        "customer_id": "redacted_live_customer",
        "merchant_id": "razorpay_test_mode",
        "mandate_id": "existing_live_mandate",
        "amount_paise": amount,
        "currency": str(normalized.get("currency") or "INR"),
        # The webhook does not expose the mandate ceiling. Equality deliberately
        # disables threshold inference instead of inventing a ceiling breach.
        "mandate_ceiling_paise": amount,
        "mandate_ceiling_observed": False,
        "payment_rail": payment_rail,
        "payment_method": method,
        "card_network": network,
        "decline_code": str(
            normalized.get("error_reason")
            or normalized.get("error_code")
            or "UNKNOWN"
        ),
        "attempt_number": 1,
        "previous_attempts": [],
        "timestamp": now.isoformat(),
        "recovery_window_expires_at": (now + timedelta(days=7)).isoformat(),
        "promise_to_pay": None,
        "retry_owner": "razorpay",
        "gateway_retry_at": normalized.get("charge_at"),
        "source_event": normalized.get("event"),
    }


def run_live_recovery(
    normalized: dict[str, Any], *, event_id: str, now: datetime,
    decision_client: DecisionClient | None = None,
) -> LiveRecoveryResult:
    event = str(normalized["event"])
    audit = AuditTrail(f"live_{event_id}")
    audit.append(
        transaction_id=f"live_{event_id}",
        event_type="razorpay_webhook_verified",
        actor="razorpay_webhook_receiver",
        reason_code=event.upper().replace(".", "_"),
        timestamp=now,
        previous_state=None,
        new_state=str(normalized.get("subscription_status") or "observed"),
        metadata={
            "subscription_id": normalized.get("subscription_id"),
            "body_fields_normalized": True,
        },
    )
    if event == "subscription.activated":
        return LiveRecoveryResult(
            "observed",
            event,
            None,
            None,
            None,
            ("Activation recorded; no recovery action is required.",),
            audit.verify(),
            tuple(item.to_dict() for item in audit.events),
        )

    transaction = _transaction(normalized, event_id, now)
    classification = _classification(normalized, transaction)
    audit.append(
        transaction_id=transaction["transaction_id"],
        event_type="root_cause_classified",
        actor="deterministic_classifier",
        reason_code=classification.rule_id,
        timestamp=now,
        previous_state=str(normalized.get("subscription_status") or "observed"),
        new_state="classified",
        metadata=classification.to_dict(),
    )
    config = load_recovery_config()
    # Groq is used only where there is a genuine intervention choice. Verified
    # charged/halted events have one evidence-bound terminal action and stay
    # deterministic, keeping payment evidence out of third-party model context.
    client = decision_client or (
        _decision_client()
        if event == "subscription.pending"
        else ScriptedDecisionClient()
    )
    agent = RecoveryAgent(client, retry_cap=config.retry_cap)
    verified_payment_id = None
    terminal_reason = None
    if event == "subscription.charged":
        verified_payment_id = normalized.get("payment_id")
        if not verified_payment_id:
            return LiveRecoveryResult(
                "needs_review",
                event,
                classification.to_dict(),
                None,
                None,
                ("Charged event lacked a payment id; recovery was not marked verified.",),
                audit.verify(),
                tuple(item.to_dict() for item in audit.events),
            )
    elif event == "subscription.halted":
        terminal_reason = "RAZORPAY_SUBSCRIPTION_HALTED"

    fallback_used = False
    try:
        turn = agent.decide_and_execute(
            transaction,
            classification,
            now=now,
            verified_payment_id=verified_payment_id,
            terminal_reason=terminal_reason,
        )
    except (LLMProviderError, AgentDecisionError):
        if client.provider != "groq":
            raise
        # Webhook availability and bounded recovery must not depend on an
        # external model. The deterministic client has the identical tool fence.
        fallback_used = True
        turn = RecoveryAgent(
            ScriptedDecisionClient(), retry_cap=config.retry_cap
        ).decide_and_execute(
            transaction,
            classification,
            now=now,
            verified_payment_id=verified_payment_id,
            terminal_reason=terminal_reason,
        )
    audit.append(
        transaction_id=transaction["transaction_id"],
        event_type="bounded_recovery_decided",
        actor=f"{turn.decision.provider}:{turn.decision.model}",
        reason_code=turn.tool_result.reason_code,
        timestamp=now,
        previous_state="classified",
        new_state=turn.tool_result.status,
        metadata={
            "permitted_tools": list(turn.permitted_tools),
            "decision": turn.decision.to_dict(),
            "tool_result": turn.tool_result.to_dict(),
        },
    )
    return LiveRecoveryResult(
        "completed",
        event,
        classification.to_dict(),
        turn.decision.to_dict(),
        turn.tool_result.to_dict(),
        tuple(filter(None, (
            "Razorpay remains the retry owner; no duplicate debit was scheduled.",
            "Notification execution is draft-only in this buildathon environment.",
            (
                "Groq was unavailable or returned an invalid decision; the same "
                "bounded policy ran with the deterministic fallback."
                if fallback_used else None
            ),
        ))),
        audit.verify(),
        tuple(item.to_dict() for item in audit.events),
    )
