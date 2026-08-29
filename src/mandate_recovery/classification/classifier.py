"""Pure, deterministic root-cause classifier.

The classifier accepts a runtime dictionary rather than a full synthetic model.
This makes evaluation-label leakage structurally harder: answer-key fields are
neither required nor inspected.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mandate_recovery.models import (
    CardNetwork, ClassificationResult, FailureCategory, PaymentRail,
)

from .rules import (
    ClassificationConfig,
    RULE_AFA_STEPUP,
    RULE_EXPIRED_CARD,
    RULE_INSUFFICIENT_FUNDS,
    RULE_OTHER,
    RULE_RUPAY_HARD_BLOCK,
    load_classification_config,
)


class ClassificationInputError(ValueError):
    """Raised when required observable transaction data is invalid or missing."""


def _required_int(record: Mapping[str, Any], field: str) -> int:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ClassificationInputError(f"{field} must be an integer")
    if value <= 0:
        raise ClassificationInputError(f"{field} must be positive")
    return value


def _required_text(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ClassificationInputError(f"{field} must be a non-empty string")
    return value.strip()


def classify(
    record: Mapping[str, Any], *, config: ClassificationConfig | None = None
) -> ClassificationResult:
    """Classify one failed payment and explain exactly which rule fired."""

    config = config or load_classification_config()
    transaction_id = _required_text(record, "transaction_id")
    amount = _required_int(record, "amount_paise")
    mandate_ceiling = _required_int(record, "mandate_ceiling_paise")
    decline_code = _required_text(record, "decline_code").upper()
    payment_rail = _required_text(record, "payment_rail").lower()
    if payment_rail not in {rail.value for rail in PaymentRail}:
        raise ClassificationInputError("payment_rail is unsupported")
    network_value = record.get("card_network")
    if network_value is not None and not isinstance(network_value, str):
        raise ClassificationInputError("card_network must be a string or null")
    network = network_value.lower() if isinstance(network_value, str) else None
    if network is not None and network not in {item.value for item in CardNetwork}:
        raise ClassificationInputError("card_network is unsupported")
    if payment_rail == PaymentRail.CARD.value and network is None:
        raise ClassificationInputError("card payment requires card_network")
    if payment_rail == PaymentRail.UPI.value and network is not None:
        raise ClassificationInputError("UPI payment must not include card_network")

    common_evidence = {
        "transaction_id": transaction_id,
        "amount_paise": amount,
        "mandate_ceiling_paise": mandate_ceiling,
        "payment_rail": payment_rail,
        "card_network": network,
        "decline_code": decline_code,
    }

    if network == CardNetwork.RUPAY.value and amount > config.regulatory_threshold_paise:
        return ClassificationResult(
            FailureCategory.RUPAY_HARD_BLOCK.value,
            RULE_RUPAY_HARD_BLOCK,
            "RuPay recurring debit is above the configured hard threshold.",
            {**common_evidence, "regulatory_threshold_paise": config.regulatory_threshold_paise},
        )

    if decline_code in config.insufficient_funds_codes:
        return ClassificationResult(
            FailureCategory.INSUFFICIENT_FUNDS.value,
            RULE_INSUFFICIENT_FUNDS,
            "Issuer decline code identifies an insufficient-funds failure.",
            {**common_evidence, "matched_decline_code": decline_code},
        )

    if decline_code in config.expired_card_codes:
        return ClassificationResult(
            FailureCategory.EXPIRED_CARD.value,
            RULE_EXPIRED_CARD,
            "Issuer decline code identifies an expired-card failure.",
            {**common_evidence, "matched_decline_code": decline_code},
        )

    if amount > mandate_ceiling and network != CardNetwork.RUPAY.value:
        return ClassificationResult(
            FailureCategory.AFA_STEPUP_REQUIRED.value,
            RULE_AFA_STEPUP,
            "Amount exceeds the mandate ceiling on a non-RuPay payment method.",
            {**common_evidence, "ceiling_excess_paise": amount - mandate_ceiling},
        )

    return ClassificationResult(
        FailureCategory.OTHER.value,
        RULE_OTHER,
        "No configured deterministic root-cause rule matched this failure.",
        common_evidence,
    )
