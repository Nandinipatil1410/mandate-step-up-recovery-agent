"""Classify a generated batch and produce honest evaluation artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.classification import classify, load_classification_config
from mandate_recovery.models import EVALUATION_FIELDS, FailureCategory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify a synthetic failed-payment batch.")
    parser.add_argument(
        "--dataset", type=Path,
        default=PROJECT_ROOT / "data" / "generated" / "failed_payments.seed-42.jsonl",
    )
    parser.add_argument(
        "--config", type=Path,
        default=PROJECT_ROOT / "config" / "classification.toml",
    )
    parser.add_argument("--run-id", default="checkpoint-2")
    return parser.parse_args()


def load_records(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as dataset:
        for line_number, line in enumerate(dataset, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON on line {line_number}: {error.msg}") from error
    if not records:
        raise ValueError("dataset is empty")
    return records


def runtime_view(record: dict[str, Any]) -> dict[str, Any]:
    """Strip evaluation labels before classification."""
    return {key: value for key, value in record.items() if key not in EVALUATION_FIELDS}


def main() -> int:
    args = parse_args()
    try:
        records = load_records(args.dataset)
        config = load_classification_config(args.config)
    except (OSError, ValueError) as error:
        print(f"Unable to start classification: {error}", file=sys.stderr)
        return 2

    output_dir = PROJECT_ROOT / "data" / "runs" / args.run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    classified_path = output_dir / "classified_transactions.jsonl"
    metrics_path = output_dir / "classification_metrics.json"
    classified_at = datetime.now(timezone.utc).isoformat()

    output_rows: list[dict[str, Any]] = []
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    per_category_total: Counter[str] = Counter()
    per_category_correct: Counter[str] = Counter()
    mismatches: list[dict[str, str]] = []

    for source in records:
        expected = source.get("failure_category")
        if expected not in {category.value for category in FailureCategory}:
            print(
                f"Record {source.get('transaction_id', '<unknown>')} has no valid ground truth",
                file=sys.stderr,
            )
            return 2
        observable = runtime_view(source)
        try:
            result = classify(observable, config=config)
        except ValueError as error:
            print(
                f"Classification failed for {source.get('transaction_id', '<unknown>')}: {error}",
                file=sys.stderr,
            )
            return 1

        matches = result.predicted_category == expected
        confusion[expected][result.predicted_category] += 1
        per_category_total[expected] += 1
        if matches:
            per_category_correct[expected] += 1
        else:
            mismatches.append({
                "transaction_id": str(source["transaction_id"]),
                "expected": expected,
                "predicted": result.predicted_category,
                "rule_id": result.rule_id,
            })
        output_rows.append({
            "transaction": observable,
            "classification": {**result.to_dict(), "classified_at": classified_at},
            "evaluation": {
                "expected_failure_category": expected,
                "matches_ground_truth": matches,
            },
        })

    with classified_path.open("w", encoding="utf-8", newline="\n") as output:
        for row in output_rows:
            output.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")

    correct = sum(per_category_correct.values())
    categories = [category.value for category in FailureCategory]
    metrics = {
        "run_id": args.run_id,
        "dataset": str(args.dataset),
        "classified_at": classified_at,
        "total": len(records),
        "correct": correct,
        "accuracy": correct / len(records),
        "per_category": {
            category: {
                "total": per_category_total[category],
                "correct": per_category_correct[category],
                "accuracy": (
                    per_category_correct[category] / per_category_total[category]
                    if per_category_total[category] else None
                ),
            }
            for category in categories
        },
        "confusion_matrix": {
            expected: {predicted: confusion[expected][predicted] for predicted in categories}
            for expected in categories
        },
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    print("Batch classification completed")
    print(f"Run ID: {args.run_id}")
    print(f"Records: {len(records)}")
    print(f"Correct: {correct}")
    print(f"Accuracy: {correct / len(records):.1%}")
    print(f"Mismatches: {len(mismatches)}")
    print(f"Classified records: {classified_path}")
    print(f"Metrics: {metrics_path}")
    print("Per-category accuracy:")
    for category in categories:
        total = per_category_total[category]
        accuracy = per_category_correct[category] / total if total else 0
        print(f"  {category}: {per_category_correct[category]}/{total} ({accuracy:.1%})")
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
