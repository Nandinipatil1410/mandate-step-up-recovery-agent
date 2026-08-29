"""Explicit, opt-in Razorpay test-mode connectivity smoke test."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.integrations import RazorpayGatewayError, RazorpayTestGateway


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch one existing Razorpay test Subscription."
    )
    parser.add_argument("--subscription-id", required=True)
    args = parser.parse_args()
    try:
        subscription = RazorpayTestGateway().fetch_subscription(args.subscription_id)
    except RazorpayGatewayError as error:
        print(f"Razorpay test smoke check failed: {error}", file=sys.stderr)
        return 1
    safe = {
        "id": subscription.get("id"),
        "entity": subscription.get("entity"),
        "status": subscription.get("status"),
        "plan_id": subscription.get("plan_id"),
    }
    print(json.dumps(safe, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
