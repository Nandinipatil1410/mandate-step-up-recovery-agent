"""Fixed, pre-approved tool declarations exposed to recovery LLMs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TOOL_SPECS: dict[str, dict[str, Any]] = {
    "request_stepup": {
        "name": "request_stepup",
        "description": "Request step-up approval on the existing mandate. Never creates a mandate.",
        "parameters": _schema({
            "mandate_id": {"type": "string"},
            "reason": {"type": "string"},
        }, ["mandate_id", "reason"]),
    },
    "offer_alternate_method": {
        "name": "offer_alternate_method",
        "description": "Offer UPI or a different card without retrying the blocked rail.",
        "parameters": _schema({"reason": {"type": "string"}}, ["reason"]),
    },
    "schedule_retry": {
        "name": "schedule_retry",
        "description": "Request one bounded retry; code enforces cap and window.",
        "parameters": _schema({"reason": {"type": "string"}}, ["reason"]),
    },
    "send_notification": {
        "name": "send_notification",
        "description": "Request a customer notification draft. Does not send it in simulation.",
        "parameters": _schema({
            "message_purpose": {"type": "string"},
            "reason": {"type": "string"},
        }, ["message_purpose", "reason"]),
    },
    "escalate_human": {
        "name": "escalate_human",
        "description": "Hand the case to a human reviewer with a reason.",
        "parameters": _schema({"reason": {"type": "string"}}, ["reason"]),
    },
    "mark_recovered": {
        "name": "mark_recovered",
        "description": "Mark recovered only when verified payment evidence is present.",
        "parameters": _schema({
            "payment_id": {"type": "string"},
            "reason": {"type": "string"},
        }, ["payment_id", "reason"]),
    },
    "mark_unrecoverable": {
        "name": "mark_unrecoverable",
        "description": "Close a case only when a terminal stopping condition exists.",
        "parameters": _schema({"reason": {"type": "string"}}, ["reason"]),
    },
}


def tool_specs(names: tuple[str, ...]) -> list[dict[str, Any]]:
    return [deepcopy(TOOL_SPECS[name]) for name in names]
