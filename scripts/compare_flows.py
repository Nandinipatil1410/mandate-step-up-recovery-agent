"""Run compliant agent and naive baseline against the same synthetic batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import fmean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.agent import RecoveryAgent
from mandate_recovery.classification import classify, load_classification_config
from mandate_recovery.llm import (
    GroqDecisionClient, LLMProviderError, OllamaDecisionClient,
    ScriptedDecisionClient,
)
from mandate_recovery.models import EVALUATION_FIELDS, parse_iso_datetime
from mandate_recovery.recovery import (
    load_recovery_config, run_compliant_action, run_naive_action, simulate_outcome,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare compliant and naive recovery flows.")
    parser.add_argument(
        "--dataset", type=Path,
        default=PROJECT_ROOT / "data" / "generated" / "failed_payments.seed-42.jsonl",
    )
    parser.add_argument("--run-id", default="checkpoint-3")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--provider", choices=("scripted", "groq", "ollama"), default="scripted")
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def runtime_view(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in EVALUATION_FIELDS}


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for row in rows:
            output.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def make_client(provider: str, config):
    if provider == "scripted":
        return ScriptedDecisionClient()
    if provider == "groq":
        return GroqDecisionClient(
            model=config.groq_model, base_url=config.groq_base_url,
            timeout_seconds=config.groq_timeout_seconds,
        )
    return OllamaDecisionClient(
        model=config.ollama_model, base_url=config.ollama_base_url,
        timeout_seconds=config.ollama_timeout_seconds,
    )


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    recovered = [row for row in rows if row["outcome"]["recovered"]]
    times = [row["outcome"]["time_to_recovery_hours"] for row in recovered]
    return {
        "transactions": len(rows),
        "recovered_count": len(recovered),
        "recovery_rate": len(recovered) / len(rows),
        "recovered_amount_paise": sum(
            row["outcome"]["recovered_amount_paise"] for row in recovered
        ),
        "average_time_to_recovery_hours": fmean(times) if times else None,
        "rejected_action_count": sum(not row["action"]["accepted"] for row in rows),
    }


def main() -> int:
    args = parse_args()
    recovery_config = load_recovery_config()
    classification_config = load_classification_config()
    try:
        client = make_client(args.provider, recovery_config)
        records = load_jsonl(args.dataset)
    except (OSError, ValueError, LLMProviderError) as error:
        print(f"Unable to start comparison: {error}", file=sys.stderr)
        return 2
    if not records:
        print("Unable to start comparison: dataset is empty", file=sys.stderr)
        return 2

    agent = RecoveryAgent(client, retry_cap=recovery_config.retry_cap)
    compliant_rows: list[dict[str, Any]] = []
    naive_rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    try:
        for source in records:
            transaction = runtime_view(source)
            classification = classify(transaction, config=classification_config)
            compliant_action, turn = run_compliant_action(
                agent, transaction, classification,
                now=parse_iso_datetime(transaction["timestamp"]),
            )
            naive_action = run_naive_action(
                transaction, classification, retry_cap=recovery_config.retry_cap,
            )
            compliant_outcome = simulate_outcome(
                transaction, classification.predicted_category,
                recovery_config.compliant_success_probability,
                seed=args.seed, action_accepted=compliant_action.accepted,
            )
            naive_outcome = simulate_outcome(
                transaction, classification.predicted_category,
                recovery_config.naive_success_probability,
                seed=args.seed, action_accepted=naive_action.accepted,
            )
            common = {
                "transaction_id": transaction["transaction_id"],
                "amount_paise": transaction["amount_paise"],
                "classified_category": classification.predicted_category,
                "classification_rule_id": classification.rule_id,
            }
            compliant_rows.append({
                **common, "flow": "compliant", "action": compliant_action.to_dict(),
                "outcome": compliant_outcome.to_dict(),
            })
            naive_rows.append({
                **common, "flow": "naive", "action": naive_action.to_dict(),
                "outcome": naive_outcome.to_dict(),
            })
            traces.append({
                "transaction_id": transaction["transaction_id"],
                "classification": classification.to_dict(),
                "agent_turn": turn.to_dict(),
                "paired_latent_customer_response": compliant_outcome.latent_customer_response,
            })
    except (ValueError, RuntimeError, LLMProviderError) as error:
        print(f"Comparison stopped safely: {error}", file=sys.stderr)
        return 1

    output_dir = PROJECT_ROOT / "data" / "runs" / args.run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "compliant_results.jsonl", compliant_rows)
    write_jsonl(output_dir / "naive_results.jsonl", naive_rows)
    write_jsonl(output_dir / "agent_traces.jsonl", traces)
    compliant_metrics, naive_metrics = summarize(compliant_rows), summarize(naive_rows)
    metrics = {
        "run_id": args.run_id,
        "seed": args.seed,
        "decision_provider": client.provider,
        "decision_model": client.model,
        "paired_simulation": True,
        "compliant": compliant_metrics,
        "naive": naive_metrics,
        "delta": {
            "recovered_count": (
                compliant_metrics["recovered_count"] - naive_metrics["recovered_count"]
            ),
            "recovery_rate_percentage_points": 100 * (
                compliant_metrics["recovery_rate"] - naive_metrics["recovery_rate"]
            ),
            "recovered_amount_paise": (
                compliant_metrics["recovered_amount_paise"]
                - naive_metrics["recovered_amount_paise"]
            ),
        },
    }
    (output_dir / "comparison_metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )

    def rupees(paise: int) -> str:
        return f"INR {paise / 100:,.2f}"

    print("Recovery-flow comparison completed")
    print(f"Provider: {client.provider} / {client.model}")
    print(f"Transactions: {len(records)}")
    print(
        f"Compliant: {compliant_metrics['recovered_count']}/{len(records)} "
        f"({compliant_metrics['recovery_rate']:.1%}), "
        f"{rupees(compliant_metrics['recovered_amount_paise'])}"
    )
    print(
        f"Naive: {naive_metrics['recovered_count']}/{len(records)} "
        f"({naive_metrics['recovery_rate']:.1%}), "
        f"{rupees(naive_metrics['recovered_amount_paise'])}"
    )
    print(
        f"Delta: {metrics['delta']['recovery_rate_percentage_points']:.1f} percentage points, "
        f"{rupees(metrics['delta']['recovered_amount_paise'])}"
    )
    print(f"Artifacts: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
