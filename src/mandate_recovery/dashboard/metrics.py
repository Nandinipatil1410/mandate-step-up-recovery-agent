"""Load and cross-check run artifacts without hardcoded dashboard metrics."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as source:
        rows = [json.loads(line) for line in source if line.strip()]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"expected JSON objects in: {path}")
    return rows


@dataclass(frozen=True)
class DashboardPaths:
    comparison_dir: Path
    lifecycle_dir: Path


@dataclass(frozen=True)
class DashboardData:
    comparison: dict[str, Any]
    lifecycle: dict[str, Any]
    lifecycle_results: list[dict[str, Any]]
    audit_events: list[dict[str, Any]]
    notifications: list[dict[str, Any]]
    category_rows: list[dict[str, Any]]
    flow_rows: list[dict[str, Any]]
    outcome_rows: list[dict[str, Any]]
    reason_rows: list[dict[str, Any]]
    transaction_ids: list[str]

    def events_for(self, transaction_id: str) -> list[dict[str, Any]]:
        return [
            event for event in self.audit_events
            if event.get("transaction_id") == transaction_id
        ]

    def notifications_for(self, transaction_id: str) -> list[dict[str, Any]]:
        return [
            row for row in self.notifications
            if row.get("transaction_id") == transaction_id
        ]


def load_dashboard_data(paths: DashboardPaths) -> DashboardData:
    comparison = _read_json(paths.comparison_dir / "comparison_metrics.json")
    lifecycle = _read_json(paths.lifecycle_dir / "lifecycle_summary.json")
    results = _read_jsonl(paths.lifecycle_dir / "lifecycle_results.jsonl")
    events = _read_jsonl(paths.lifecycle_dir / "audit_events.jsonl")
    notifications = _read_jsonl(paths.lifecycle_dir / "notifications.jsonl")

    transaction_count = len(results)
    if transaction_count == 0:
        raise ValueError("lifecycle results are empty")
    if lifecycle.get("transactions") != transaction_count:
        raise ValueError("lifecycle summary transaction count does not match results")
    recovered = sum(bool(row.get("recovered")) for row in results)
    recovered_paise = sum(int(row.get("recovered_amount_paise", 0)) for row in results)
    if lifecycle.get("recovered_count") != recovered:
        raise ValueError("lifecycle recovered count does not match results")
    if lifecycle.get("recovered_amount_paise") != recovered_paise:
        raise ValueError("lifecycle recovered amount does not match results")

    category_totals: Counter[str] = Counter()
    category_recovered: Counter[str] = Counter()
    for row in results:
        category = str(row["category"])
        category_totals[category] += 1
        if row.get("recovered"):
            category_recovered[category] += 1
    category_rows = [
        {
            "category": category,
            "transactions": total,
            "recovered": category_recovered[category],
            "unresolved": total - category_recovered[category],
            "recovery_rate": category_recovered[category] / total,
        }
        for category, total in sorted(category_totals.items())
    ]

    flow_rows = []
    for flow in ("compliant", "naive"):
        metrics = comparison[flow]
        flow_rows.append({
            "flow": flow.title(),
            "recovery_rate_percent": float(metrics["recovery_rate"]) * 100,
            "recovered_count": int(metrics["recovered_count"]),
            "recovered_amount_paise": int(metrics["recovered_amount_paise"]),
        })

    outcome_counts = Counter(str(row["final_state"]) for row in results)
    outcome_rows = [
        {"state": state, "transactions": count}
        for state, count in sorted(outcome_counts.items())
    ]
    reason_counts = Counter(
        str(row["unresolved_reason"])
        for row in results if row.get("unresolved_reason")
    )
    reason_rows = [
        {"reason": reason, "transactions": count}
        for reason, count in reason_counts.most_common()
    ]

    events_by_transaction: dict[str, int] = defaultdict(int)
    for event in events:
        events_by_transaction[str(event.get("transaction_id"))] += 1
    transaction_ids = sorted(
        (str(row["transaction_id"]) for row in results),
        key=lambda transaction_id: (-events_by_transaction[transaction_id], transaction_id),
    )
    return DashboardData(
        comparison=comparison,
        lifecycle=lifecycle,
        lifecycle_results=results,
        audit_events=events,
        notifications=notifications,
        category_rows=category_rows,
        flow_rows=flow_rows,
        outcome_rows=outcome_rows,
        reason_rows=reason_rows,
        transaction_ids=transaction_ids,
    )
