from __future__ import annotations

import hashlib
import hmac
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.integrations import WebhookVerificationError
from mandate_recovery.llm import LLMProviderError
from mandate_recovery.webhooks import (
    WebhookEventStore, configured_live_decision_provider,
    process_razorpay_webhook, run_live_recovery,
)


class UnavailableGroqClient:
    provider = "groq"
    model = "unavailable-test-model"

    def choose_tool(self, context, tools):
        raise LLMProviderError("simulated provider outage")


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
                    "charge_at": 1788537600,
                }},
                "payment": {"entity": {
                    "id": "pay_test", "status": "failed", "amount": 150000,
                    "currency": "INR", "error_code": "BAD_REQUEST_ERROR",
                    "error_reason": "payment_failed", "method": "emandate",
                }},
            },
        }, separators=(",", ":")).encode()

    def signature(self, body: bytes) -> str:
        return hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()

    def test_live_provider_uses_groq_when_key_is_configured(self) -> None:
        with patch.dict(
            "os.environ",
            {"GROQ_API_KEY": "test-only", "LIVE_DECISION_PROVIDER": "auto"},
            clear=True,
        ):
            self.assertEqual("groq", configured_live_decision_provider())

    def test_live_provider_falls_back_safely_when_groq_is_unavailable(self) -> None:
        normalized = {
            "event": "subscription.pending",
            "subscription_id": "sub_test",
            "subscription_status": "pending",
            "customer_id": "cust_test",
            "charge_at": 1788537600,
            "payment_id": "pay_test",
            "payment_status": "failed",
            "payment_method": "emandate",
            "amount_paise": 150000,
            "currency": "INR",
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "payment_failed",
        }
        result = run_live_recovery(
            normalized,
            event_id="event_fallback",
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
            decision_client=UnavailableGroqClient(),
        )
        self.assertEqual("scripted", result.decision["provider"])
        self.assertTrue(any("fallback" in note for note in result.safety_notes))

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
            self.assertEqual("completed", first.processing_status)
            self.assertEqual("send_notification", first.recovery["tool_result"]["tool_name"])
            self.assertEqual(
                first.recovery["tool_result"], duplicate.recovery["tool_result"]
            )
            recent = store.recent_recoveries(limit=5)
            self.assertEqual(1, len(recent))
            self.assertEqual("other", recent[0]["classification"]["predicted_category"])
            self.assertEqual("send_notification", recent[0]["tool_result"]["tool_name"])
            self.assertEqual("scripted", recent[0]["decision_provider"])
            self.assertTrue(recent[0]["audit_chain_valid"])
            self.assertEqual(3, recent[0]["audit_event_count"])

    def test_charged_event_requires_payment_evidence_and_marks_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = WebhookEventStore(Path(directory) / "events.sqlite3")
            body = self.payload("subscription.charged")
            with patch.dict("os.environ", {"GROQ_API_KEY": "test-only"}, clear=True):
                processed = process_razorpay_webhook(
                    body=body, signature=self.signature(body), event_id="event_charged",
                    secret=self.secret, store=store,
                    received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
            self.assertEqual("mark_recovered", processed.recovery["tool_result"]["tool_name"])
            self.assertEqual("VERIFIED_PAYMENT", processed.recovery["tool_result"]["reason_code"])
            self.assertEqual("scripted", processed.recovery["decision"]["provider"])
            self.assertTrue(processed.recovery["audit_chain_valid"])

    def test_halted_event_closes_only_with_terminal_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = WebhookEventStore(Path(directory) / "events.sqlite3")
            body = self.payload("subscription.halted")
            processed = process_razorpay_webhook(
                body=body, signature=self.signature(body), event_id="event_halted",
                secret=self.secret, store=store,
                received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            self.assertEqual("mark_unrecoverable", processed.recovery["tool_result"]["tool_name"])
            self.assertEqual(
                "RAZORPAY_SUBSCRIPTION_HALTED",
                processed.recovery["tool_result"]["reason_code"],
            )

    def test_activated_event_is_observed_without_recovery_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = WebhookEventStore(Path(directory) / "events.sqlite3")
            body = self.payload("subscription.activated")
            processed = process_razorpay_webhook(
                body=body, signature=self.signature(body), event_id="event_activated",
                secret=self.secret, store=store,
                received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            self.assertEqual("observed", processed.processing_status)
            self.assertIsNone(processed.recovery["tool_result"])

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
