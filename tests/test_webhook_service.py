from __future__ import annotations

import hashlib
import hmac
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.integrations import WebhookVerificationError
from mandate_recovery.webhooks import WebhookEventStore, process_razorpay_webhook


class WebhookServiceTests(unittest.TestCase):
    secret = "webhook-test-secret"

    def payload(self, event: str = "subscription.pending") -> bytes:
        return json.dumps({
            "event": event,
            "payload": {
                "subscription": {"entity": {
                    "id": "sub_test", "status": "pending",
                    "customer_id": "cust_test", "plan_id": "plan_test",
                    "paid_count": 1, "remaining_count": 11,
                }},
                "payment": {"entity": {
                    "id": "pay_test", "status": "failed", "amount": 150000,
                    "currency": "INR", "error_code": "BAD_REQUEST_ERROR",
                    "error_reason": "payment_failed",
                }},
            },
        }, separators=(",", ":")).encode()

    def signature(self, body: bytes) -> str:
        return hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()

    def test_valid_event_is_recorded_once_and_duplicate_is_acknowledged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = WebhookEventStore(Path(directory) / "events.sqlite3")
            body = self.payload()
            first = process_razorpay_webhook(
                body=body, signature=self.signature(body), event_id="event_1",
                secret=self.secret, store=store,
                received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            duplicate = process_razorpay_webhook(
                body=body, signature=self.signature(body), event_id="event_1",
                secret=self.secret, store=store,
                received_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            )
            self.assertFalse(first.duplicate)
            self.assertTrue(duplicate.duplicate)
            self.assertEqual(1, store.count())

    def test_invalid_signature_is_rejected_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = WebhookEventStore(Path(directory) / "events.sqlite3")
            with self.assertRaises(WebhookVerificationError):
                process_razorpay_webhook(
                    body=self.payload(), signature="invalid", event_id="event_1",
                    secret=self.secret, store=store,
                )
            self.assertEqual(0, store.count())

    def test_event_id_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = WebhookEventStore(Path(directory) / "events.sqlite3")
            body = self.payload()
            with self.assertRaisesRegex(ValueError, "event-id"):
                process_razorpay_webhook(
                    body=body, signature=self.signature(body), event_id="",
                    secret=self.secret, store=store,
                )

    def test_unsupported_signed_event_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = WebhookEventStore(Path(directory) / "events.sqlite3")
            body = self.payload("subscription.cancelled")
            with self.assertRaisesRegex(ValueError, "unsupported"):
                process_razorpay_webhook(
                    body=body, signature=self.signature(body), event_id="event_2",
                    secret=self.secret, store=store,
                )


if __name__ == "__main__":
    unittest.main()
