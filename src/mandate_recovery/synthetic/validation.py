"""Schema and business-invariant validation for generated batches."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from mandate_recovery.models import (
    CardNetwork, CorrectAction, FailureCategory, PaymentRail,
    SyntheticTransaction, parse_iso_datetime,
)


@dataclass(frozen=True)
class ValidationIssue:
    transaction_id: str
    field: str
    message: str


def validate_transaction(
    transaction: SyntheticTransaction, *, regulatory_threshold_paise: int = 1_500_000
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def add(field: str, message: str) -> None:
        issues.append(ValidationIssue(transaction.transaction_id, field, message))

    if transaction.amount_paise <= 0:
        add("amount_paise", "must be positive")
    if transaction.currency != "INR":
        add("currency", "checkpoint 1 supports INR only")
    if transaction.mandate_ceiling_paise <= 0:
        add("mandate_ceiling_paise", "must be positive")
    if transaction.attempt_number != len(transaction.previous_attempts) + 1:
        add("attempt_number", "must follow the number of previous attempts")
    expected_numbers = list(range(1, transaction.attempt_number))
    actual_numbers = [attempt.attempt_number for attempt in transaction.previous_attempts]
    if actual_numbers != expected_numbers:
        add("previous_attempts", "attempt numbers must be sequential")

    try:
        created_at = parse_iso_datetime(transaction.timestamp)
        expires_at = parse_iso_datetime(transaction.recovery_window_expires_at)
        if expires_at <= created_at:
            add("recovery_window_expires_at", "must be later than timestamp")
    except ValueError as error:
        add("timestamp", str(error))

    try:
        rail = PaymentRail(transaction.payment_rail)
    except ValueError:
        add("payment_rail", "unsupported payment rail")
        rail = None
    if rail is PaymentRail.CARD and transaction.card_network is None:
        add("card_network", "card transactions require a card network")
    if rail is PaymentRail.UPI and transaction.card_network is not None:
        add("card_network", "UPI transactions must not have a card network")
    if transaction.card_network is not None:
        try:
            CardNetwork(transaction.card_network)
        except ValueError:
            add("card_network", "unsupported card network")

    try:
        category = FailureCategory(transaction.failure_category)
    except ValueError:
        add("failure_category", "unsupported failure category")
        return issues

    expected_action = {
        FailureCategory.AFA_STEPUP_REQUIRED: CorrectAction.REQUEST_STEPUP,
        FailureCategory.RUPAY_HARD_BLOCK: CorrectAction.OFFER_ALTERNATE_METHOD,
        FailureCategory.INSUFFICIENT_FUNDS: CorrectAction.SCHEDULE_RETRY,
        FailureCategory.EXPIRED_CARD: CorrectAction.SCHEDULE_RETRY,
        FailureCategory.OTHER: CorrectAction.ESCALATE_HUMAN,
    }[category]
    if transaction.correct_action != expected_action.value:
        add("correct_action", f"must be {expected_action.value} for {category.value}")

    if category is FailureCategory.AFA_STEPUP_REQUIRED:
        if transaction.amount_paise <= transaction.mandate_ceiling_paise:
            add("amount_paise", "AFA record must exceed mandate ceiling")
        if transaction.card_network == CardNetwork.RUPAY.value:
            add("card_network", "AFA step-up category excludes RuPay")
    elif category is FailureCategory.RUPAY_HARD_BLOCK:
        if transaction.card_network != CardNetwork.RUPAY.value:
            add("card_network", "RuPay hard block requires RuPay")
        if transaction.amount_paise <= regulatory_threshold_paise:
            add("amount_paise", "RuPay hard block must be above threshold")
    elif category is FailureCategory.INSUFFICIENT_FUNDS:
        if transaction.decline_code != "INSUFFICIENT_FUNDS":
            add("decline_code", "insufficient-funds category requires matching code")
    elif category is FailureCategory.EXPIRED_CARD:
        if transaction.decline_code != "CARD_EXPIRED":
            add("decline_code", "expired-card category requires matching code")
    return issues


def validate_batch(
    transactions: Iterable[SyntheticTransaction], *, minimum_count: int = 100,
    maximum_count: int = 300, regulatory_threshold_paise: int = 1_500_000,
) -> list[ValidationIssue]:
    records = list(transactions)
    issues: list[ValidationIssue] = []
    if not minimum_count <= len(records) <= maximum_count:
        issues.append(ValidationIssue(
            "<batch>", "count", f"must be between {minimum_count} and {maximum_count}"
        ))
    identifiers = Counter(record.transaction_id for record in records)
    for identifier, count in identifiers.items():
        if count > 1:
            issues.append(ValidationIssue(identifier, "transaction_id", "must be unique"))
    for transaction in records:
        issues.extend(validate_transaction(
            transaction, regulatory_threshold_paise=regulatory_threshold_paise
        ))

    category_counts = Counter(record.failure_category for record in records)
    missing = {category.value for category in FailureCategory} - set(category_counts)
    for category in sorted(missing):
        issues.append(ValidationIssue("<batch>", "failure_category", f"missing {category}"))
    afa_count = category_counts[FailureCategory.AFA_STEPUP_REQUIRED.value]
    other_counts = [count for category, count in category_counts.items()
                    if category != FailureCategory.AFA_STEPUP_REQUIRED.value]
    if other_counts and afa_count <= max(other_counts):
        issues.append(ValidationIssue(
            "<batch>", "failure_category", "afa_stepup_required must be dominant"
        ))
    if records and all(record.ground_truth_recoverable for record in records):
        issues.append(ValidationIssue(
            "<batch>", "ground_truth_recoverable", "must include an unrecoverable case"
        ))
    return issues
