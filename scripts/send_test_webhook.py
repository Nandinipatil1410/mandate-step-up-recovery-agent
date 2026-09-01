"""Send a signed synthetic subscription event to a local or deployed receiver."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.environment import load_project_environment


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the signed webhook receiver.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhooks/razorpay")
    parser.add_argument(
        "--event", choices=(
            "subscription.pending", "subscription.charged",
            "subscription.halted", "subscription.activated",
        ), default="subscription.pending",
    )
    args = parser.parse_args()
    load_project_environment(PROJECT_ROOT)
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
    if not secret:
        print("RAZORPAY_WEBHOOK_SECRET is not configured", file=sys.stderr)
        return 2
    status = {
        "subscription.pending": "pending",
        "subscription.charged": "active",
        "subscription.halted": "halted",
        "subscription.activated": "active",
    }[args.event]
    body = json.dumps({
        "event": args.event,
        "payload": {"subscription": {"entity": {
            "id": "sub_buildathon_probe", "status": status,
            "customer_id": "cust_buildathon_probe", "plan_id": "plan_buildathon_probe",
            "paid_count": 1, "remaining_count": 11,
        }}},
    }, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        args.url, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": signature,
            "X-Razorpay-Event-Id": f"probe_{uuid4().hex}",
            "User-Agent": "mandate-recovery-buildathon/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        print(f"Webhook probe failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
