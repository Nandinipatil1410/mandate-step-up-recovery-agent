"""Credential-safe Groq and Razorpay Test Mode integration smoke checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.agent import RecoveryAgent
from mandate_recovery.classification import classify, load_classification_config
from mandate_recovery.environment import load_project_environment
from mandate_recovery.integrations import RazorpayGatewayError, RazorpayTestGateway
from mandate_recovery.llm import GroqDecisionClient, LLMProviderError
from mandate_recovery.models import EVALUATION_FIELDS, parse_iso_datetime
from mandate_recovery.notifications import GroqNotificationProvider, NotificationGenerator
from mandate_recovery.recovery import load_recovery_config


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def runtime_view(record: dict) -> dict:
    return {key: value for key, value in record.items() if key not in EVALUATION_FIELDS}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Test Groq and Razorpay credentials without printing secrets."
    )
    parser.add_argument(
        "--dataset", type=Path,
        default=PROJECT_ROOT / "data" / "generated" / "failed_payments.seed-42.jsonl",
    )
    parser.add_argument(
        "--create-payment-link", action="store_true",
        help="Create exactly one INR 1 Standard Payment Link in Razorpay Test Mode.",
    )
    args = parser.parse_args()
    load_project_environment(PROJECT_ROOT)

    try:
        config = load_recovery_config()
        classification_config = load_classification_config()
        candidates = [runtime_view(record) for record in load_jsonl(args.dataset)]
        transaction = next(
            record for record in candidates
            if classify(record, config=classification_config).predicted_category
            == "afa_stepup_required"
        )
        classification = classify(transaction, config=classification_config)
        groq = GroqDecisionClient(
            model=config.groq_model, base_url=config.groq_base_url,
            timeout_seconds=config.groq_timeout_seconds,
        )
        turn = RecoveryAgent(groq, retry_cap=config.retry_cap).decide_and_execute(
            transaction, classification,
            now=parse_iso_datetime(transaction["timestamp"]),
        )
        notification = NotificationGenerator(GroqNotificationProvider(
            model=config.groq_model, base_url=config.groq_base_url,
            timeout_seconds=config.groq_timeout_seconds,
        )).generate(
            purpose="stepup", transaction_id=transaction["transaction_id"],
            amount_paise=transaction["amount_paise"],
            context_reason=turn.tool_result.reason_code,
        )
        gateway = RazorpayTestGateway()
        links = gateway.fetch_payment_links(count=1)
    except (OSError, ValueError, StopIteration, LLMProviderError,
            RazorpayGatewayError, RuntimeError) as error:
        print(f"Integration smoke check failed safely: {error}", file=sys.stderr)
        return 1

    print("Groq decision: PASS")
    print(f"  model={groq.model}")
    print(f"  tool={turn.tool_result.tool_name}")
    print(f"  accepted={turn.tool_result.accepted}")
    print("Groq notification: PASS")
    print(f"  validation={notification.validation_status}")
    print(f"  draft={notification.response}")
    print("Razorpay Test Mode connectivity: PASS")
    print(f"  entity={links.get('entity', 'collection')}")
    print(f"  returned_items={len(links.get('items', []))}")

    if args.create_payment_link:
        try:
            reference_id = f"buildathon-smoke-{uuid4().hex[:12]}"
            link = gateway.create_alternate_payment_link(
                amount_paise=100, currency="INR", reference_id=reference_id,
                description="Buildathon alternate payment method smoke test",
            )
        except RazorpayGatewayError as error:
            print(f"Payment Link creation failed safely: {error}", file=sys.stderr)
            return 1
        print("Razorpay Standard Test Payment Link: CREATED")
        print(f"  id={link.get('id')}")
        print(f"  status={link.get('status')}")
        print(f"  short_url={link.get('short_url')}")
        print(f"  reference_id={reference_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
