"""Generate and validate a reproducible JSONL checkpoint dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.synthetic import generate_batch, load_config, validate_batch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate labeled recurring-payment failures.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--count", type=int)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "generator.toml")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def serialize(records: list[object]) -> bytes:
    lines = [
        json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"))
        for record in records
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    count = args.count if args.count is not None else config.default_count
    output = args.output or PROJECT_ROOT / "data" / "generated" / f"failed_payments.seed-{args.seed}.jsonl"
    try:
        records = generate_batch(count=count, seed=args.seed, config=config)
    except ValueError as error:
        print(f"Generation failed: {error}", file=sys.stderr)
        return 2

    issues = validate_batch(
        records, minimum_count=config.minimum_count, maximum_count=config.maximum_count,
        regulatory_threshold_paise=config.regulatory_threshold_paise,
    )
    if issues:
        print(f"Validation failed with {len(issues)} issue(s):", file=sys.stderr)
        for issue in issues[:20]:
            print(f"- {issue.transaction_id} [{issue.field}]: {issue.message}", file=sys.stderr)
        return 1

    payload = serialize(records)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    category_counts = Counter(record.failure_category for record in records)
    rail_counts = Counter(record.payment_rail for record in records)
    recoverable = sum(record.ground_truth_recoverable for record in records)

    print("Synthetic dataset generated successfully")
    print(f"Output: {output}")
    print(f"Records: {len(records)}")
    print(f"Seed: {args.seed}")
    print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")
    print("Categories:")
    for category, number in sorted(category_counts.items()):
        print(f"  {category}: {number} ({number / len(records):.1%})")
    print("Payment rails:")
    for rail, number in sorted(rail_counts.items()):
        print(f"  {rail}: {number} ({number / len(records):.1%})")
    print(f"Ground-truth recoverable: {recoverable} ({recoverable / len(records):.1%})")
    print(f"Ground-truth unrecoverable: {len(records) - recoverable}")
    print("Validation errors: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
