from __future__ import annotations

import hashlib
import hmac
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.agent import RecoveryAgent
from mandate_recovery.audit import AuditTrail, verify_audit_jsonl
from mandate_recovery.classification import load_classification_config
from mandate_recovery.integrations import (
    RazorpayGatewayError, RazorpayTestGateway, WebhookVerificationError,
    normalize_subscription_event, verify_webhook_signature,
)
from mandate_recovery.llm import ScriptedDecisionClient
from mandate_recovery.notifications import (
    NotificationGenerator, TemplateNotificationProvider,
)
from mandate_recovery.promises import PromiseState, PromiseTracker
from mandate_recovery.recovery import RecoveryLifecycleRunner, load_recovery_config
from mandate_recovery.scheduling import RetryScheduler, evaluate_stopping_rules
from mandate_recovery.synthetic import generate_batch, load_config


UTC = timezone.utc


class UnsafeNotificationProvider:
    provider = "test"
    model = "unsafe"

    def draft(self, prompt: str, *, purpose: str) -> str:
        return "Please share your OTP and CVV."


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.recovery_config = load_recovery_config(
            PROJECT_ROOT / "config" / "recovery.toml"
        )
        cls.classification_config = load_classification_config(
            PROJECT_ROOT / "config" / "classification.toml"
        )
        generator_config = load_config(PROJECT_ROOT / "config" / "generator.toml")
        cls.records = generate_batch(count=200, seed=42, config=generator_config)

    def scheduler(self):
        return RetryScheduler(
            retry_cap=3, backoff_hours=(24, 72), pre_debit_notice_hours=24
        )

    def test_retry_schedule_uses_24_then_72_hour_backoff(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        first = self.scheduler().schedule(
            attempt_number=1, now=now,
            recovery_window_expires_at=now + timedelta(days=7),
        )
        second = self.scheduler().schedule(
            attempt_number=2, now=first.retry_at,
            recovery_window_expires_at=now + timedelta(days=7),
        )
        self.assertEqual(now + timedelta(hours=24), first.retry_at)
        self.assertEqual(first.retry_at + timedelta(hours=72), second.retry_at)
        self.assertEqual(3, second.next_attempt)

    def test_retry_cap_and_window_are_terminal(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        capped = evaluate_stopping_rules(
            attempt_number=3, retry_cap=3, now=now,
            recovery_window_expires_at=now + timedelta(days=1),
        )
        expired = evaluate_stopping_rules(
            attempt_number=1, retry_cap=3, now=now,
            recovery_window_expires_at=now,
        )
        self.assertEqual("RETRY_CAP_REACHED", capped.reason_code)
        self.assertEqual("RECOVERY_WINDOW_EXPIRED", expired.reason_code)

    def test_retry_outside_window_is_rejected(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        result = self.scheduler().schedule(
            attempt_number=2, now=now,
            recovery_window_expires_at=now + timedelta(hours=48),
        )
        self.assertFalse(result.accepted)
        self.assertEqual("NEXT_RETRY_OUTSIDE_WINDOW", result.reason_code)

    def test_promise_allows_exactly_one_follow_up(self) -> None:
        tracker = PromiseTracker()
        now = datetime(2026, 1, 2, tzinfo=UTC)
        state = PromiseState("missed", now - timedelta(days=1), 0)
        self.assertEqual("follow_up", tracker.evaluate(state, now=now).action)
        followed = tracker.record_follow_up(state)
        self.assertEqual("stop_follow_up", tracker.evaluate(followed, now=now).action)
        with self.assertRaises(ValueError):
            tracker.record_follow_up(followed)

    def test_template_notification_logs_prompt_and_safe_response(self) -> None:
        draft = NotificationGenerator(TemplateNotificationProvider()).generate(
            purpose="stepup", transaction_id="txn_1", amount_paise=1_600_000,
            context_reason="AFA required",
        )
        self.assertIn("Transaction: txn_1", draft.prompt)
        self.assertIn("approval", draft.response)
        self.assertEqual("passed", draft.validation_status)

    def test_unsafe_notification_is_flagged(self) -> None:
        draft = NotificationGenerator(UnsafeNotificationProvider()).generate(
            purpose="stepup", transaction_id="txn_1", amount_paise=1_600_000,
            context_reason="AFA required",
        )
        self.assertEqual("rejected_sensitive_request", draft.validation_status)

    def test_audit_chain_detects_tampering(self) -> None:
        trail = AuditTrail("test")
        now = datetime(2026, 1, 1, tzinfo=UTC)
        trail.append(
            transaction_id="txn_1", event_type="classification", actor="test",
            reason_code="RULE", timestamp=now, previous_state="failed",
            new_state="classified",
        )
        trail.append(
            transaction_id="txn_1", event_type="action", actor="test",
            reason_code="ACTION", timestamp=now, previous_state="classified",
            new_state="acted",
        )
        self.assertTrue(trail.verify())
        trail.events[0] = replace(trail.events[0], reason_code="TAMPERED")
        self.assertFalse(trail.verify())

    def test_persisted_audit_can_be_verified_independently(self) -> None:
        trail = AuditTrail("persisted-test")
        trail.append(
            transaction_id="txn_1", event_type="classification", actor="test",
            reason_code="RULE", timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            previous_state="failed", new_state="classified",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            trail.write_jsonl(path)
            self.assertEqual((True, 1, None), verify_audit_jsonl(path))
            path.write_text(path.read_text().replace("RULE", "TAMPERED"))
            valid, event_number, _ = verify_audit_jsonl(path)
            self.assertFalse(valid)
            self.assertEqual(1, event_number)

    def test_webhook_signature_and_normalization(self) -> None:
        body = json.dumps({
            "event": "subscription.pending",
            "payload": {"subscription": {"entity": {
                "id": "sub_test", "status": "pending", "customer_id": "cust_test"
            }}},
        }).encode()
        secret = "test-secret"
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        verify_webhook_signature(body, signature, secret)
        normalized = normalize_subscription_event(body)
        self.assertEqual("subscription.pending", normalized["event"])
        self.assertEqual("sub_test", normalized["subscription_id"])
        with self.assertRaises(WebhookVerificationError):
            verify_webhook_signature(body, "bad-signature", secret)

    def test_razorpay_gateway_rejects_live_credentials(self) -> None:
        with self.assertRaises(RazorpayGatewayError):
            RazorpayTestGateway(key_id="rzp_live_not_allowed", key_secret="secret")

    def test_full_batch_has_valid_audit_and_bounded_attempts(self) -> None:
        audit = AuditTrail("lifecycle-test")
        runner = RecoveryLifecycleRunner(
            agent=RecoveryAgent(ScriptedDecisionClient(), retry_cap=3),
            notification_generator=NotificationGenerator(TemplateNotificationProvider()),
            recovery_config=self.recovery_config,
            classification_config=self.classification_config,
            audit_trail=audit,
            seed=42,
        )
        results = [runner.run(record.to_dict()) for record in self.records]
        self.assertTrue(audit.verify())
        self.assertTrue(all(result.final_attempt_number <= 3 for result in results))
        self.assertTrue(any(result.recovered for result in results))
        self.assertTrue(any(not result.recovered for result in results))
        self.assertTrue(all(
            draft["validation_status"] == "passed"
            for draft in runner.notification_drafts
        ))

        schedules = {
            event.event_id: event
            for event in audit.events
            if event.event_type == "retry_scheduled"
        }
        notices = [
            event for event in audit.events
            if event.event_type == "notification_drafted"
            and event.reason_code == "RETRY_NOTICE"
        ]
        self.assertTrue(notices)
        for notice in notices:
            preceding = [
                event for event in schedules.values()
                if event.transaction_id == notice.transaction_id
                and event.event_id < notice.event_id
            ][-1]
            self.assertEqual(preceding.metadata["notice_at"], notice.timestamp)

    def test_missed_promises_never_receive_more_than_one_follow_up(self) -> None:
        audit = AuditTrail("promise-test")
        runner = RecoveryLifecycleRunner(
            agent=RecoveryAgent(ScriptedDecisionClient(), retry_cap=3),
            notification_generator=NotificationGenerator(TemplateNotificationProvider()),
            recovery_config=self.recovery_config,
            classification_config=self.classification_config,
            audit_trail=audit,
            seed=42,
        )
        for record in self.records:
            runner.run(record.to_dict())
        followups = {}
        for event in audit.events:
            if event.event_type == "promise_follow_up":
                followups[event.transaction_id] = followups.get(event.transaction_id, 0) + 1
        self.assertTrue(followups)
        self.assertTrue(all(count == 1 for count in followups.values()))


if __name__ == "__main__":
    unittest.main()
