"""Independently verify a persisted checkpoint audit hash chain."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.audit import verify_audit_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a recovery audit JSONL chain.")
    parser.add_argument(
        "path", nargs="?", type=Path,
        default=PROJECT_ROOT / "data" / "runs" / "checkpoint-4" / "audit_events.jsonl",
    )
    args = parser.parse_args()
    valid, count, error = verify_audit_jsonl(args.path)
    if not valid:
        print(f"INVALID audit chain at event {count}: {error}", file=sys.stderr)
        return 1
    print(f"VALID audit chain: {count} events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
