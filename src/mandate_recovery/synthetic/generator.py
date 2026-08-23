"""Seeded generator for labeled failed recurring-payment records."""

from __future__ import annotations

import random
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from mandate_recovery.models import (
    CardNetwork,
    CorrectAction,
    FailureCategory,
    PaymentRail,
    PreviousAttempt,
    PromiseToPay,
    SyntheticTransaction,
)

GENERATOR_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "generator.toml"


@dataclass(frozen=True)
class GenerationConfig:
    default_count: int
    minimum_count: int
    maximum_count: int
    currency: str
    regulatory_threshold_paise: int
    recovery_window_days: int
    category_weights: Mapping[str, float]
    recovery_rates: Mapping[str, float]


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> GenerationConfig:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    dataset = raw["dataset"]
    return GenerationConfig(
        default_count=int(dataset["default_count"]),
        minimum_count=int(dataset["minimum_count"]),
        maximum_count=int(dataset["maximum_count"]),
        currency=str(dataset["currency"]),
        regulatory_threshold_paise=int(dataset["regulatory_threshold_paise"]),
        recovery_window_days=int(dataset["recovery_window_days"]),
        category_weights=dict(raw["category_weights"]),
        recovery_rates=dict(raw["recovery_rates"]),
    )


def _category_plan(
    rng: random.Random, config: GenerationConfig, count: int
) -> list[FailureCategory]:
    """Allocate configured proportions exactly, then seed-shuffle the batch."""
    weights = dict(config.category_weights)
    if set(weights) != {category.value for category in FailureCategory}:
        raise ValueError("category_weights must define every failure category exactly once")
    if any(weight <= 0 for weight in weights.values()):
        raise ValueError("category weights must be positive")
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 1e-9:
        raise ValueError("category weights must sum to 1.0")

    raw_counts = {category: count * weight for category, weight in weights.items()}
    allocated = {category: int(raw_count) for category, raw_count in raw_counts.items()}
    remaining = count - sum(allocated.values())
    remainders = sorted(
        weights,
        key=lambda category: (raw_counts[category] - allocated[category], category),
        reverse=True,
    )
    for category in remainders[:remaining]:
        allocated[category] += 1

    plan = [
        FailureCategory(category)
        for category, category_count in allocated.items()
        for _ in range(category_count)
    ]
    rng.shuffle(plan)
    return plan


def _amount(rng: random.Random, minimum: int, maximum: int) -> int:
    return rng.randint(minimum // 100, maximum // 100) * 100


def _failure_facts(
    category: FailureCategory, rng: random.Random, threshold: int
) -> tuple[int, int, PaymentRail, CardNetwork | None, str, CorrectAction]:
    if category is FailureCategory.AFA_STEPUP_REQUIRED:
        ceiling = rng.choice([10_000_00, 12_000_00, threshold])
        return (
            _amount(rng, ceiling + 100, 30_000_00), ceiling, PaymentRail.CARD,
            rng.choice([CardNetwork.VISA, CardNetwork.MASTERCARD]),
            "MANDATE_LIMIT_EXCEEDED", CorrectAction.REQUEST_STEPUP,
        )
    if category is FailureCategory.RUPAY_HARD_BLOCK:
        return (
            _amount(rng, threshold + 100, 30_000_00),
            rng.choice([threshold, 20_000_00, 25_000_00]), PaymentRail.CARD,
            CardNetwork.RUPAY, "RECURRING_LIMIT_NOT_SUPPORTED",
            CorrectAction.OFFER_ALTERNATE_METHOD,
        )
    if category is FailureCategory.INSUFFICIENT_FUNDS:
        ceiling = rng.choice([threshold, 25_000_00, 50_000_00])
        rail = rng.choice([PaymentRail.CARD, PaymentRail.UPI])
        return (
            _amount(rng, 499_00, min(14_999_00, ceiling)), ceiling, rail,
            rng.choice(list(CardNetwork)) if rail is PaymentRail.CARD else None,
            "INSUFFICIENT_FUNDS", CorrectAction.SCHEDULE_RETRY,
        )
    if category is FailureCategory.EXPIRED_CARD:
        ceiling = rng.choice([threshold, 25_000_00, 50_000_00])
        return (
            _amount(rng, 499_00, min(14_999_00, ceiling)), ceiling,
            PaymentRail.CARD, rng.choice(list(CardNetwork)), "CARD_EXPIRED",
            CorrectAction.SCHEDULE_RETRY,
        )
    ceiling = rng.choice([threshold, 25_000_00, 50_000_00])
    rail = rng.choice([PaymentRail.CARD, PaymentRail.UPI])
    return (
        _amount(rng, 499_00, min(14_999_00, ceiling)), ceiling, rail,
        rng.choice(list(CardNetwork)) if rail is PaymentRail.CARD else None,
        rng.choice(["BANK_TECHNICAL_ERROR", "UNKNOWN_DECLINE", "ISSUER_UNAVAILABLE"]),
        CorrectAction.ESCALATE_HUMAN,
    )


def _attempt_history(
    rng: random.Random, timestamp: datetime, decline_code: str
) -> tuple[int, tuple[PreviousAttempt, ...]]:
    attempt_number = rng.choices([1, 2, 3], weights=[0.65, 0.25, 0.10], k=1)[0]
    attempts = tuple(
        PreviousAttempt(
            attempt_number=number,
            attempted_at=(timestamp - timedelta(days=attempt_number - number)).isoformat(),
            outcome="failed",
            decline_code=decline_code,
        )
        for number in range(1, attempt_number)
    )
    return attempt_number, attempts


def _promise_to_pay(rng: random.Random, timestamp: datetime) -> PromiseToPay | None:
    state = rng.choices(["none", "active", "missed"], weights=[0.82, 0.12, 0.06], k=1)[0]
    if state == "none":
        return None
    if state == "active":
        return PromiseToPay(
            "active", (timestamp + timedelta(days=rng.choice([1, 2, 3]))).isoformat(), 0
        )
    return PromiseToPay(
        "missed", (timestamp - timedelta(days=1)).isoformat(), rng.choice([0, 1])
    )


def generate_batch(
    *, count: int, seed: int, config: GenerationConfig | None = None
) -> list[SyntheticTransaction]:
    """Generate an ordered, reproducible batch for ``seed`` and ``count``."""
    config = config or load_config()
    if not config.minimum_count <= count <= config.maximum_count:
        raise ValueError(
            f"count must be between {config.minimum_count} and {config.maximum_count}"
        )

    rng = random.Random(seed)
    base_time = datetime(2026, 8, 22, 9, 0, tzinfo=timezone.utc)
    records: list[SyntheticTransaction] = []
    categories = _category_plan(rng, config, count)
    for index, category in enumerate(categories, start=1):
        amount, ceiling, rail, network, decline_code, action = _failure_facts(
            category, rng, config.regulatory_threshold_paise
        )
        timestamp = base_time + timedelta(minutes=index - 1)
        attempt_number, history = _attempt_history(rng, timestamp, decline_code)
        mandate_suffix = rng.randint(100_000, 999_999)
        records.append(
            SyntheticTransaction(
                schema_version=SCHEMA_VERSION,
                generator_version=GENERATOR_VERSION,
                transaction_id=f"txn_{seed}_{index:04d}",
                customer_id=f"cust_{rng.randint(1, max(20, count // 2)):04d}",
                merchant_id=f"merchant_{rng.randint(1, 8):03d}",
                mandate_id=f"mandate_{mandate_suffix}",
                umrn=f"UMRN{mandate_suffix}" if rng.random() < 0.35 else None,
                amount_paise=amount,
                currency=config.currency,
                mandate_ceiling_paise=ceiling,
                payment_rail=rail.value,
                card_network=network.value if network else None,
                decline_code=decline_code,
                attempt_number=attempt_number,
                previous_attempts=history,
                timestamp=timestamp.isoformat(),
                recovery_window_expires_at=(timestamp + timedelta(days=config.recovery_window_days)).isoformat(),
                promise_to_pay=_promise_to_pay(rng, timestamp),
                failure_category=category.value,
                correct_action=action.value,
                ground_truth_recoverable=rng.random() < config.recovery_rates[category.value],
            )
        )
    return records
