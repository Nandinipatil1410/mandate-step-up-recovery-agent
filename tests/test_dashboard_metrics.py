from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.dashboard import DashboardPaths, load_dashboard_data


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def write_jsonl(path: Path, rows) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


class DashboardMetricsTests(unittest.TestCase):
    def fixture(self, root: Path) -> DashboardPaths:
        comparison = root / "checkpoint-3"
        lifecycle = root / "checkpoint-4"
        comparison.mkdir()
        lifecycle.mkdir()
        write_json(comparison / "comparison_metrics.json", {
            "compliant": {
                "recovery_rate": 0.5, "recovered_count": 1,
                "recovered_amount_paise": 20000,
            },
            "naive": {
                "recovery_rate": 0.0, "recovered_count": 0,
                "recovered_amount_paise": 0,
            },
            "delta": {
                "recovery_rate_percentage_points": 50.0,
                "recovered_amount_paise": 20000,
            },
        })
        write_json(lifecycle / "lifecycle_summary.json", {
            "transactions": 2, "recovered_count": 1,
            "recovered_amount_paise": 20000,
        })
        write_jsonl(lifecycle / "lifecycle_results.jsonl", [
            {
                "transaction_id": "txn_1", "category": "afa_stepup_required",
                "final_state": "recovered", "recovered": True,
                "recovered_amount_paise": 20000, "unresolved_reason": None,
            },
            {
                "transaction_id": "txn_2", "category": "other",
                "final_state": "escalated", "recovered": False,
                "recovered_amount_paise": 0,
                "unresolved_reason": "HUMAN_REVIEW_REQUIRED",
            },
        ])
        write_jsonl(lifecycle / "audit_events.jsonl", [
            {"transaction_id": "txn_1", "event_type": "classification"},
            {"transaction_id": "txn_1", "event_type": "tool_execution"},
            {"transaction_id": "txn_2", "event_type": "classification"},
        ])
        write_jsonl(lifecycle / "notifications.jsonl", [
            {"transaction_id": "txn_1", "purpose": "stepup"},
        ])
        return DashboardPaths(comparison, lifecycle)

    def test_computes_categories_outcomes_and_transaction_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data = load_dashboard_data(self.fixture(Path(directory)))
        self.assertEqual(2, len(data.category_rows))
        self.assertEqual("Compliant", data.flow_rows[0]["flow"])
        self.assertEqual("txn_1", data.transaction_ids[0])
        self.assertEqual(2, len(data.events_for("txn_1")))
        self.assertEqual(1, len(data.notifications_for("txn_1")))
        self.assertEqual(
            [{"reason": "HUMAN_REVIEW_REQUIRED", "transactions": 1}],
            data.reason_rows,
        )

    def test_rejects_summary_that_disagrees_with_raw_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            summary_path = paths.lifecycle_dir / "lifecycle_summary.json"
            summary = json.loads(summary_path.read_text())
            summary["recovered_count"] = 2
            write_json(summary_path, summary)
            with self.assertRaisesRegex(ValueError, "recovered count"):
                load_dashboard_data(paths)


if __name__ == "__main__":
    unittest.main()
