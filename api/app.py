"""FastAPI receiver for signed Razorpay subscription webhooks."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.environment import load_project_environment
from mandate_recovery.integrations import WebhookVerificationError
from mandate_recovery.webhooks import (
    WebhookEventStore, configured_live_decision_provider,
    process_razorpay_webhook,
)

load_project_environment(PROJECT_ROOT)

app = FastAPI(
    title="Mandate Recovery Webhook",
    description="Verified Razorpay Test Mode subscription-event intake.",
    version="1.0.0",
)


def event_store() -> WebhookEventStore:
    configured = os.environ.get("WEBHOOK_DB_PATH")
    path = Path(configured) if configured else (
        PROJECT_ROOT / "data" / "webhooks" / "razorpay_events.sqlite3"
    )
    return WebhookEventStore(path)


@app.get("/health")
def health() -> dict[str, object]:
    configured = bool(os.environ.get("RAZORPAY_WEBHOOK_SECRET"))
    return {
        "status": "ok" if configured else "configuration_required",
        "webhook_secret_configured": configured,
        "decision_provider": configured_live_decision_provider(),
    }


@app.get("/recoveries/recent")
def recent_recoveries(limit: int = 20) -> dict[str, object]:
    """Return a PII-minimized Test Mode recovery feed for the demo dashboard."""
    recoveries = event_store().recent_recoveries(limit=limit)
    return {"count": len(recoveries), "recoveries": recoveries}


@app.post("/webhooks/razorpay")
async def receive_razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(default=""),
    x_razorpay_event_id: str = Header(default=""),
) -> dict[str, object]:
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="webhook secret is not configured")
    body = await request.body()
    try:
        processed = process_razorpay_webhook(
            body=body, signature=x_razorpay_signature,
            event_id=x_razorpay_event_id, secret=secret, store=event_store(),
        )
    except WebhookVerificationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "status": "duplicate" if processed.duplicate else "accepted",
        **processed.to_dict(),
    }
