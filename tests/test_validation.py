from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.models import FailureCategory
from mandate_recovery.synthetic import generate_batch, load_config, validate_transaction


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config(PROJECT_ROOT / "config" / "generator.toml")
        cls.records = generate_batch(count=200, seed=42, config=cls.config)

    def record_for(self, category: FailureCategory):
        return next(record for record in self.records if record.failure_category == category.value)

    def test_rejects_afa_record_not_above_ceiling(self) -> None:
        record = self.record_for(FailureCategory.AFA_STEPUP_REQUIRED)
        issues = validate_transaction(replace(record, amount_paise=record.mandate_ceiling_paise))
        self.assertTrue(any(issue.field == "amount_paise" for issue in issues))

    def test_rejects_rupay_record_at_exact_threshold(self) -> None:
        record = self.record_for(FailureCategory.RUPAY_HARD_BLOCK)
        issues = validate_transaction(replace(record, amount_paise=1_500_000))
        self.assertTrue(any("above threshold" in issue.message for issue in issues))

    def test_rejects_upi_record_with_card_network(self) -> None:
        record = self.record_for(FailureCategory.INSUFFICIENT_FUNDS)
        issues = validate_transaction(replace(record, payment_rail="upi", card_network="visa"))
        self.assertTrue(any("UPI" in issue.message for issue in issues))

    def test_rejects_incorrect_action_label(self) -> None:
        record = self.record_for(FailureCategory.EXPIRED_CARD)
        issues = validate_transaction(replace(record, correct_action="escalate_human"))
        self.assertTrue(any(issue.field == "correct_action" for issue in issues))


if __name__ == "__main__":
    unittest.main()
