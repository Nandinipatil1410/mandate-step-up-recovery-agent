"""Execute full checkpoint-4 recovery lifecycles with a simulated clock."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import fmean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.agent import RecoveryAgent
from mandate_recovery.environment import load_project_environment
from mandate_recovery.audit import AuditTrail
from mandate_recovery.classification import load_classification_config
from mandate_recovery.llm import (
    GroqDecisionClient, OllamaDecisionClient, ScriptedDecisionClient,
)
from mandate_recovery.notifications import (
    GroqNotificationProvider, NotificationGenerator, TemplateNotificationProvider,
)
from mandate_recovery.recovery import RecoveryLifecycleRunner, load_recovery_config

load_project_environment(PROJECT_ROOT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run complete bounded recovery lifecycles.")
    parser.add_argument(
        "--dataset", type=Path,
        default=PROJECT_ROOT / "data" / "generated" / "failed_payments.seed-42.jsonl",
    )
    parser.add_argument("--run-id", default="checkpoint-4")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--decision-provider", choices=("scripted", "groq", "ollama"), default="scripted")
    parser.add_argument("--notification-provider", choices=("template", "groq"), default="template")
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for row in rows:
            output.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def decision_client(name, config):
    if name == "scripted":
        return ScriptedDecisionClient()
    if name == "groq":
        return GroqDecisionClient(
            model=config.groq_model, base_url=config.groq_base_url,
            timeout_seconds=config.groq_timeout_seconds,
        )
    return OllamaDecisionClient(
        model=config.ollama_model, base_url=config.ollama_base_url,
        timeout_seconds=config.ollama_timeout_seconds,
    )


def notification_client(name, config):
    if name == "template":
        return TemplateNotificationProvider()
    return GroqNotificationProvider(
        model=config.groq_model, base_url=config.groq_base_url,
        timeout_seconds=config.groq_timeout_seconds,
    )


def main() -> int:
    args = parse_args()
    try:
        records = load_jsonl(args.dataset)
        recovery_config = load_recovery_config()
        classifier_config = load_classification_config()
        decision = decision_client(args.decision_provider, recovery_config)
        notifier = notification_client(args.notification_provider, recovery_config)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Unable to start recovery run: {error}", file=sys.stderr)
        return 2
    if not records:
        print("Unable to start recovery run: dataset is empty", file=sys.stderr)
        return 2

    audit = AuditTrail(args.run_id)
    runner = RecoveryLifecycleRunner(
        agent=RecoveryAgent(decision, retry_cap=recovery_config.retry_cap),
        notification_generator=NotificationGenerator(notifier),
        recovery_config=recovery_config,
        classification_config=classifier_config,
        audit_trail=audit,
        seed=args.seed,
    )
    try:
        results = [runner.run(record) for record in records]
    except (ValueError, RuntimeError) as error:
        print(f"Recovery run stopped safely: {error}", file=sys.stderr)
        return 1

    output_dir = PROJECT_ROOT / "data" / "runs" / args.run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    result_rows = [result.to_dict() for result in results]
    write_jsonl(output_dir / "lifecycle_results.jsonl", result_rows)
    write_jsonl(output_dir / "notifications.jsonl", runner.notification_drafts)
    audit.write_jsonl(output_dir / "audit_events.jsonl")

    recovered = [result for result in results if result.recovered]
    unresolved = Counter(
        result.unresolved_reason for result in results if not result.recovered
    )
    final_states = Counter(result.final_state for result in results)
    summary = {
        "run_id": args.run_id,
        "seed": args.seed,
        "decision_provider": decision.provider,
        "decision_model": decision.model,
        "notification_provider": notifier.provider,
        "notification_model": notifier.model,
        "transactions": len(results),
        "recovered_count": len(recovered),
        "recovery_rate": len(recovered) / len(results),
        "recovered_amount_paise": sum(item.recovered_amount_paise for item in recovered),
        "average_time_to_recovery_hours": (
            fmean(item.time_to_recovery_hours for item in recovered) if recovered else None
        ),
        "final_states": dict(sorted(final_states.items())),
        "unresolved_reasons": dict(sorted(unresolved.items(), key=lambda item: str(item[0]))),
        "notification_count": len(runner.notification_drafts),
        "audit_event_count": len(audit.events),
        "audit_chain_valid": audit.verify(),
    }
    (output_dir / "lifecycle_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    if not summary["audit_chain_valid"]:
        print("Audit-chain verification failed", file=sys.stderr)
        return 1

    print("Recovery lifecycle run completed")
    print(f"Transactions: {len(results)}")
    print(f"Recovered: {len(recovered)} ({len(recovered) / len(results):.1%})")
    print(f"Recovered amount: INR {summary['recovered_amount_paise'] / 100:,.2f}")
    print(f"Notifications drafted: {summary['notification_count']}")
    print(f"Audit events: {summary['audit_event_count']} (chain valid: True)")
    print(f"Artifacts: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
