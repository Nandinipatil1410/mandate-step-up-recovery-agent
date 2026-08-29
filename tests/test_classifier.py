from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.classification import (
    ClassificationInputError, classify, load_classification_config,
)
from mandate_recovery.classification.rules import (
    RULE_AFA_STEPUP, RULE_EXPIRED_CARD, RULE_INSUFFICIENT_FUNDS,
    RULE_OTHER, RULE_RUPAY_HARD_BLOCK,
)
from mandate_recovery.models import EVALUATION_FIELDS, FailureCategory
from mandate_recovery.synthetic import generate_batch, load_config


class ClassifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.classification_config = load_classification_config(
            PROJECT_ROOT / "config" / "classification.toml"
        )
        generator_config = load_config(PROJECT_ROOT / "config" / "generator.toml")
        cls.records = generate_batch(count=200, seed=42, config=generator_config)

    def base_record(self, **overrides):
        record = {
            "transaction_id": "txn_boundary",
            "amount_paise": 1_000_000,
            "mandate_ceiling_paise": 1_500_000,
            "payment_rail": "card",
            "card_network": "visa",
            "decline_code": "UNKNOWN_DECLINE",
        }
        record.update(overrides)
        return record

    def classify(self, record):
        return classify(record, config=self.classification_config)

    def test_exactly_threshold_is_not_rupay_hard_block(self) -> None:
        result = self.classify(self.base_record(
            amount_paise=1_500_000, card_network="rupay"
        ))
        self.assertEqual(FailureCategory.OTHER.value, result.predicted_category)
        self.assertEqual(RULE_OTHER, result.rule_id)

    def test_rupay_above_threshold_is_hard_block(self) -> None:
        result = self.classify(self.base_record(
            amount_paise=1_500_001, mandate_ceiling_paise=2_000_000,
            card_network="rupay",
        ))
        self.assertEqual(FailureCategory.RUPAY_HARD_BLOCK.value, result.predicted_category)
        self.assertEqual(RULE_RUPAY_HARD_BLOCK, result.rule_id)

    def test_non_rupay_above_ceiling_requires_stepup(self) -> None:
        result = self.classify(self.base_record(
            amount_paise=1_500_001, mandate_ceiling_paise=1_500_000
        ))
        self.assertEqual(FailureCategory.AFA_STEPUP_REQUIRED.value, result.predicted_category)
        self.assertEqual(RULE_AFA_STEPUP, result.rule_id)
        self.assertEqual(1, result.evidence["ceiling_excess_paise"])

    def test_upi_above_ceiling_requires_stepup(self) -> None:
        result = self.classify(self.base_record(
            amount_paise=1_500_001, mandate_ceiling_paise=1_500_000,
            payment_rail="upi", card_network=None,
        ))
        self.assertEqual(FailureCategory.AFA_STEPUP_REQUIRED.value, result.predicted_category)

    def test_funds_code_is_explainable(self) -> None:
        result = self.classify(self.base_record(decline_code="low_balance"))
        self.assertEqual(FailureCategory.INSUFFICIENT_FUNDS.value, result.predicted_category)
        self.assertEqual(RULE_INSUFFICIENT_FUNDS, result.rule_id)
        self.assertEqual("LOW_BALANCE", result.evidence["matched_decline_code"])

    def test_expired_card_code_is_explainable(self) -> None:
        result = self.classify(self.base_record(decline_code="expired_card"))
        self.assertEqual(FailureCategory.EXPIRED_CARD.value, result.predicted_category)
        self.assertEqual(RULE_EXPIRED_CARD, result.rule_id)

    def test_explicit_decline_code_precedes_afa_rule(self) -> None:
        result = self.classify(self.base_record(
            amount_paise=1_600_000, mandate_ceiling_paise=1_500_000,
            decline_code="INSUFFICIENT_FUNDS",
        ))
        self.assertEqual(FailureCategory.INSUFFICIENT_FUNDS.value, result.predicted_category)

    def test_rupay_hard_block_has_highest_precedence(self) -> None:
        result = self.classify(self.base_record(
            amount_paise=1_600_000, card_network="rupay",
            decline_code="CARD_EXPIRED",
        ))
        self.assertEqual(FailureCategory.RUPAY_HARD_BLOCK.value, result.predicted_category)

    def test_unknown_code_falls_back_with_named_rule(self) -> None:
        result = self.classify(self.base_record())
        self.assertEqual(FailureCategory.OTHER.value, result.predicted_category)
        self.assertEqual(RULE_OTHER, result.rule_id)
        self.assertTrue(result.reason)

    def test_classifier_ignores_injected_answer_key_fields(self) -> None:
        observable = self.base_record(decline_code="INSUFFICIENT_FUNDS")
        poisoned = copy.deepcopy(observable)
        poisoned.update({
            "failure_category": "expired_card",
            "correct_action": "mark_recovered",
            "ground_truth_recoverable": False,
        })
        self.assertEqual(self.classify(observable), self.classify(poisoned))
        self.assertTrue(EVALUATION_FIELDS.issubset(poisoned))

    def test_missing_required_field_is_rejected(self) -> None:
        record = self.base_record()
        del record["amount_paise"]
        with self.assertRaises(ClassificationInputError):
            self.classify(record)

    def test_invalid_payment_rail_is_rejected(self) -> None:
        with self.assertRaises(ClassificationInputError):
            self.classify(self.base_record(payment_rail="cash"))

    def test_card_without_network_is_rejected(self) -> None:
        with self.assertRaises(ClassificationInputError):
            self.classify(self.base_record(card_network=None))

    def test_upi_with_card_network_is_rejected(self) -> None:
        with self.assertRaises(ClassificationInputError):
            self.classify(self.base_record(payment_rail="upi", card_network="visa"))

    def test_generated_batch_matches_ground_truth(self) -> None:
        mismatches = []
        for record in self.records:
            result = self.classify(record.to_runtime_dict())
            if result.predicted_category != record.failure_category:
                mismatches.append(record.transaction_id)
        self.assertEqual([], mismatches)


if __name__ == "__main__":
    unittest.main()
