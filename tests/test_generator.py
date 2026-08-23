from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.models import EVALUATION_FIELDS, FailureCategory
from mandate_recovery.synthetic import generate_batch, load_config, validate_batch


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config(PROJECT_ROOT / "config" / "generator.toml")

    def test_same_seed_produces_identical_records(self) -> None:
        self.assertEqual(
            generate_batch(count=200, seed=42, config=self.config),
            generate_batch(count=200, seed=42, config=self.config),
        )

    def test_different_seed_changes_records(self) -> None:
        self.assertNotEqual(
            generate_batch(count=100, seed=42, config=self.config),
            generate_batch(count=100, seed=43, config=self.config),
        )

    def test_count_must_be_in_configured_range(self) -> None:
        with self.assertRaises(ValueError):
            generate_batch(count=99, seed=42, config=self.config)
        with self.assertRaises(ValueError):
            generate_batch(count=301, seed=42, config=self.config)

    def test_batch_is_valid_and_contains_all_categories(self) -> None:
        records = generate_batch(count=200, seed=42, config=self.config)
        self.assertEqual([], validate_batch(records))
        self.assertEqual(
            {category.value for category in FailureCategory},
            {record.failure_category for record in records},
        )

    def test_afa_is_dominant_for_review_seed(self) -> None:
        counts = Counter(
            record.failure_category
            for record in generate_batch(count=200, seed=42, config=self.config)
        )
        afa_count = counts[FailureCategory.AFA_STEPUP_REQUIRED.value]
        self.assertGreater(
            afa_count,
            max(count for category, count in counts.items()
                if category != FailureCategory.AFA_STEPUP_REQUIRED.value),
        )

    def test_category_counts_follow_configured_weights(self) -> None:
        records = generate_batch(count=200, seed=42, config=self.config)
        counts = Counter(record.failure_category for record in records)
        self.assertEqual(100, counts[FailureCategory.AFA_STEPUP_REQUIRED.value])
        self.assertEqual(30, counts[FailureCategory.RUPAY_HARD_BLOCK.value])
        self.assertEqual(30, counts[FailureCategory.INSUFFICIENT_FUNDS.value])
        self.assertEqual(20, counts[FailureCategory.EXPIRED_CARD.value])
        self.assertEqual(20, counts[FailureCategory.OTHER.value])

    def test_runtime_view_removes_answer_key_fields(self) -> None:
        record = generate_batch(count=100, seed=42, config=self.config)[0]
        self.assertTrue(EVALUATION_FIELDS.isdisjoint(record.to_runtime_dict()))
        self.assertTrue(EVALUATION_FIELDS.issubset(record.to_dict()))

    def test_batch_contains_recoverable_and_unrecoverable_cases(self) -> None:
        records = generate_batch(count=200, seed=42, config=self.config)
        self.assertEqual(
            {True, False}, {record.ground_truth_recoverable for record in records}
        )


if __name__ == "__main__":
    unittest.main()
