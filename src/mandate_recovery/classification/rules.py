"""Configuration and named rules for root-cause classification."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CLASSIFICATION_CONFIG = (
    Path(__file__).resolve().parents[3] / "config" / "classification.toml"
)

RULE_RUPAY_HARD_BLOCK = "R001_RUPAY_ABOVE_THRESHOLD"
RULE_INSUFFICIENT_FUNDS = "R002_INSUFFICIENT_FUNDS_CODE"
RULE_EXPIRED_CARD = "R003_EXPIRED_CARD_CODE"
RULE_AFA_STEPUP = "R004_NON_RUPAY_ABOVE_MANDATE_CEILING"
RULE_OTHER = "R999_UNRECOGNIZED_FAILURE"

RULE_PRECEDENCE = (
    RULE_RUPAY_HARD_BLOCK,
    RULE_INSUFFICIENT_FUNDS,
    RULE_EXPIRED_CARD,
    RULE_AFA_STEPUP,
    RULE_OTHER,
)


@dataclass(frozen=True)
class ClassificationConfig:
    regulatory_threshold_paise: int
    insufficient_funds_codes: frozenset[str]
    expired_card_codes: frozenset[str]


def load_classification_config(
    path: Path = DEFAULT_CLASSIFICATION_CONFIG,
) -> ClassificationConfig:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)["rules"]
    threshold = int(raw["regulatory_threshold_paise"])
    if threshold <= 0:
        raise ValueError("regulatory_threshold_paise must be positive")
    funds_codes = frozenset(str(code).upper() for code in raw["insufficient_funds_codes"])
    expired_codes = frozenset(str(code).upper() for code in raw["expired_card_codes"])
    if not funds_codes or not expired_codes:
        raise ValueError("decline-code sets must not be empty")
    if funds_codes & expired_codes:
        raise ValueError("decline-code sets must not overlap")
    return ClassificationConfig(threshold, funds_codes, expired_codes)
