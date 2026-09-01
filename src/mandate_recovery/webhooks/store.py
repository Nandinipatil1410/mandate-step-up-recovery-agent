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
