"""Framework-neutral webhook processing with verification before parsing."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from mandate_recovery.integrations import (
    normalize_subscription_event, verify_webhook_signature,
)

from .store import WebhookEventStore
from .recovery import run_live_recovery


@dataclass(frozen=True)
class ProcessedWebhook:
    event_id: str
    event: str
    subscription_id: str | None
    duplicate: bool
    processing_status: str
    recovery: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def process_razorpay_webhook(
    *, body: bytes, signature: str, event_id: str, secret: str,
    store: WebhookEventStore, received_at: datetime | None = None,
) -> ProcessedWebhook:
    if not event_id.strip():
        raise ValueError("x-razorpay-event-id header is required")
    verify_webhook_signature(body, signature, secret)
    normalized = normalize_subscription_event(body)
    timestamp = received_at or datetime.now(timezone.utc)
    inserted = store.record(
        event_id=event_id, normalized=normalized,
        received_at=timestamp.isoformat(),
        body_sha256=hashlib.sha256(body).hexdigest(),
    )
    recovery = store.recovery_for(event_id)
    if recovery is None:
        try:
            recovery = run_live_recovery(
                normalized, event_id=event_id, now=timestamp
            ).to_dict()
            store.set_recovery(
                event_id=event_id,
                recovery=recovery,
                processed_at=timestamp.isoformat(),
            )
        except Exception as error:
            store.set_processing_error(
                event_id=event_id,
                error=f"{type(error).__name__}: {error}",
                processed_at=timestamp.isoformat(),
            )
            # Raising produces a non-2xx response, so Razorpay can retry the same
            # event id. The normalized intake remains durable for that replay.
            raise
    return ProcessedWebhook(
        event_id=event_id,
        event=str(normalized["event"]),
        subscription_id=normalized.get("subscription_id"),
        duplicate=not inserted,
        processing_status=str(recovery["processing_status"]),
        recovery=recovery,
    )
