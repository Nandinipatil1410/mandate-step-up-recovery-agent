"""Small SQLite store for idempotent, inspectable webhook intake."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


class WebhookEventStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS webhook_events (
                    event_id TEXT PRIMARY KEY,
                    event_name TEXT NOT NULL,
                    subscription_id TEXT,
                    subscription_status TEXT,
                    received_at TEXT NOT NULL,
                    body_sha256 TEXT NOT NULL,
                    normalized_json TEXT NOT NULL
                )
            """)
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(webhook_events)")
            }
            for name, declaration in {
                "recovery_json": "TEXT",
                "processed_at": "TEXT",
                "processing_error": "TEXT",
            }.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE webhook_events ADD COLUMN {name} {declaration}"
                    )
            connection.commit()

    def record(
        self, *, event_id: str, normalized: dict[str, Any],
        received_at: str, body_sha256: str,
    ) -> bool:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO webhook_events (
                    event_id, event_name, subscription_id, subscription_status,
                    received_at, body_sha256, normalized_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id, normalized["event"], normalized.get("subscription_id"),
                    normalized.get("subscription_status"), received_at, body_sha256,
                    json.dumps(normalized, sort_keys=True, separators=(",", ":")),
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def count(self) -> int:
        with closing(self._connect()) as connection:
            return int(connection.execute(
                "SELECT COUNT(*) FROM webhook_events"
            ).fetchone()[0])

    def recovery_for(self, event_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT recovery_json FROM webhook_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None or row["recovery_json"] is None:
            return None
        return dict(json.loads(row["recovery_json"]))

    def set_recovery(
        self, *, event_id: str, recovery: dict[str, Any], processed_at: str
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE webhook_events
                SET recovery_json = ?, processed_at = ?, processing_error = NULL
                WHERE event_id = ?
                """,
                (
                    json.dumps(recovery, sort_keys=True, separators=(",", ":")),
                    processed_at,
                    event_id,
                ),
            )
            connection.commit()

    def set_processing_error(
        self, *, event_id: str, error: str, processed_at: str
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE webhook_events
                SET processed_at = ?, processing_error = ?
                WHERE event_id = ?
                """,
                (processed_at, error[:500], event_id),
            )
            connection.commit()

    def recent_recoveries(self, *, limit: int = 20) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 100))
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT event_name, subscription_id, subscription_status,
                       received_at, recovery_json, processing_error
                FROM webhook_events
                ORDER BY received_at DESC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            recovery = (
                json.loads(row["recovery_json"])
                if row["recovery_json"] is not None
                else None
            )
            subscription_id = str(row["subscription_id"] or "unknown")
            masked_id = (
                subscription_id
                if len(subscription_id) <= 12
                else f"{subscription_id[:8]}...{subscription_id[-4:]}"
            )
            results.append({
                "event": row["event_name"],
                "subscription_id": masked_id,
                "subscription_status": row["subscription_status"],
                "received_at": row["received_at"],
                "processing_status": (
                    recovery.get("processing_status")
                    if isinstance(recovery, dict)
                    else "failed" if row["processing_error"] else "pending"
                ),
                "classification": (
                    recovery.get("classification") if isinstance(recovery, dict) else None
                ),
                "tool_result": (
                    recovery.get("tool_result") if isinstance(recovery, dict) else None
                ),
                "processing_error": bool(row["processing_error"]),
                "audit_chain_valid": (
                    recovery.get("audit_chain_valid")
                    if isinstance(recovery, dict)
                    else None
                ),
                "audit_event_count": (
                    len(recovery.get("audit_events", []))
                    if isinstance(recovery, dict)
                    else 0
                ),
            })
        return results
