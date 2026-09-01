"""Signature verification and normalization for selected Razorpay webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


class WebhookVerificationError(ValueError):
    pass


SUPPORTED_SUBSCRIPTION_EVENTS = frozenset({
    "subscription.pending",
    "subscription.charged",
    "subscription.halted",
    "subscription.activated",
})


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
    if event_name not in SUPPORTED_SUBSCRIPTION_EVENTS:
        raise ValueError(f"unsupported subscription event: {event_name}")
    payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
    return {
        "source": "razorpay_test_webhook",
        "event": event_name,
        "subscription_id": subscription.get("id"),
        "subscription_status": subscription.get("status"),
        "customer_id": subscription.get("customer_id"),
        "plan_id": subscription.get("plan_id"),
        "paid_count": subscription.get("paid_count"),
        "remaining_count": subscription.get("remaining_count"),
        "charge_at": subscription.get("charge_at"),
        "payment_id": payment.get("id"),
        "payment_status": payment.get("status"),
        "amount_paise": payment.get("amount"),
        "currency": payment.get("currency"),
        "error_code": payment.get("error_code"),
        "error_reason": payment.get("error_reason"),
    }
