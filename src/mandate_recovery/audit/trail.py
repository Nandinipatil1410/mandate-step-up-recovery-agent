"""Append-only, hash-chained audit trail for every recovery decision."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    run_id: str
    transaction_id: str
    event_type: str
    actor: str
    reason_code: str
    timestamp: str
    previous_state: str | None
    new_state: str
    metadata: dict[str, Any]
    previous_event_hash: str | None
    event_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditTrail:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.events: list[AuditEvent] = []

    def append(
        self, *, transaction_id: str, event_type: str, actor: str,
        reason_code: str, timestamp: datetime, previous_state: str | None,
        new_state: str, metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        sequence = len(self.events) + 1
        previous_hash = self.events[-1].event_hash if self.events else None
        body = {
            "event_id": f"evt_{sequence:06d}",
            "run_id": self.run_id,
            "transaction_id": transaction_id,
            "event_type": event_type,
            "actor": actor,
            "reason_code": reason_code,
            "timestamp": timestamp.isoformat(),
            "previous_state": previous_state,
            "new_state": new_state,
            "metadata": metadata or {},
            "previous_event_hash": previous_hash,
        }
        event_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        event = AuditEvent(**body, event_hash=event_hash)
        self.events.append(event)
        return event

    def verify(self) -> bool:
        previous_hash = None
        for event in self.events:
            body = event.to_dict()
            recorded_hash = body.pop("event_hash")
            if body["previous_event_hash"] != previous_hash:
                return False
            calculated = hashlib.sha256(
                json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            ).hexdigest()
            if calculated != recorded_hash:
                return False
            previous_hash = recorded_hash
        return True

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as output:
            for event in self.events:
                output.write(json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":")) + "\n")


def verify_audit_jsonl(path: Path) -> tuple[bool, int, str | None]:
    """Verify a persisted chain without trusting the process that wrote it."""
    previous_hash = None
    event_count = 0
    try:
        with path.open("r", encoding="utf-8") as source:
            for event_count, line in enumerate(source, start=1):
                body = json.loads(line)
                recorded_hash = body.pop("event_hash")
                if body.get("previous_event_hash") != previous_hash:
                    return False, event_count, "previous hash does not match"
                calculated = hashlib.sha256(
                    json.dumps(
                        body, sort_keys=True, separators=(",", ":"), default=str
                    ).encode("utf-8")
                ).hexdigest()
                if calculated != recorded_hash:
                    return False, event_count, "event content hash does not match"
                previous_hash = recorded_hash
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        return False, event_count, str(error)
    return True, event_count, None
