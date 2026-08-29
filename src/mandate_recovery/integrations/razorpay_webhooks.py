"""Signature verification and normalization for selected Razorpay webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


class WebhookVerificationError(ValueError):
    pass


def verify_webhook_signature(body: bytes, signature: str, secret: str) -> None:
    if not secret:
        raise WebhookVerificationError("webhook secret is required")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise WebhookVerificationError("invalid Razorpay webhook signature")


def normalize_subscription_event(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
        event_name = str(payload["event"])
        subscription = payload["payload"]["subscription"]["entity"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("invalid subscription webhook payload") from error
    return {
        "source": "razorpay_test_webhook",
        "event": event_name,
        "subscription_id": subscription.get("id"),
        "subscription_status": subscription.get("status"),
        "customer_id": subscription.get("customer_id"),
        "raw_entity": subscription,
    }
