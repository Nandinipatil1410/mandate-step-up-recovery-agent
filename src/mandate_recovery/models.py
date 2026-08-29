"""Shared checkpoint-1 data contracts.

Money is represented as integer paise throughout the project. Evaluation fields
are stored on synthetic records but are removed by ``to_runtime_dict``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class FailureCategory(StrEnum):
    AFA_STEPUP_REQUIRED = "afa_stepup_required"
    RUPAY_HARD_BLOCK = "rupay_hard_block"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    EXPIRED_CARD = "expired_card"
    OTHER = "other"


class PaymentRail(StrEnum):
    CARD = "card"
    UPI = "upi"


class CardNetwork(StrEnum):
    VISA = "visa"
    MASTERCARD = "mastercard"
    RUPAY = "rupay"


class CorrectAction(StrEnum):
    REQUEST_STEPUP = "request_stepup"
    OFFER_ALTERNATE_METHOD = "offer_alternate_method"
    SCHEDULE_RETRY = "schedule_retry"
    ESCALATE_HUMAN = "escalate_human"


@dataclass(frozen=True)
class PreviousAttempt:
    attempt_number: int
    attempted_at: str
    outcome: str
    decline_code: str


@dataclass(frozen=True)
class PromiseToPay:
    status: str
    promised_payment_at: str
    follow_up_count: int


EVALUATION_FIELDS = frozenset(
    {"failure_category", "correct_action", "ground_truth_recoverable"}
)


@dataclass(frozen=True)
class SyntheticTransaction:
    schema_version: str
    generator_version: str
    transaction_id: str
    customer_id: str
    merchant_id: str
    mandate_id: str
    umrn: str | None
    amount_paise: int
    currency: str
    mandate_ceiling_paise: int
    payment_rail: str
    card_network: str | None
    decline_code: str
    attempt_number: int
    previous_attempts: tuple[PreviousAttempt, ...]
    timestamp: str
    recovery_window_expires_at: str
    promise_to_pay: PromiseToPay | None
    failure_category: str
    correct_action: str
    ground_truth_recoverable: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the complete synthetic record, including evaluation labels."""
        return asdict(self)

    def to_runtime_dict(self) -> dict[str, Any]:
        """Return only fields a production-like runtime is allowed to observe."""
        record = self.to_dict()
        for field in EVALUATION_FIELDS:
            record.pop(field, None)
        return record


@dataclass(frozen=True)
class ClassificationResult:
    """Explainable output from the deterministic root-cause classifier."""

    predicted_category: str
    rule_id: str
    reason: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AgentDecision:
    provider: str
    model: str
    rationale: str
    tool_calls: tuple[ToolCall, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    accepted: bool
    status: str
    reason_code: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and require timezone information."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed
