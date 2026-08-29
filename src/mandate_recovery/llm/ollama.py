"""Ollama local-model tool-calling fallback."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from mandate_recovery.models import AgentDecision, ToolCall

from .base import LLMProviderError


class OllamaDecisionClient:
    provider = "ollama"

    def __init__(self, *, model: str, base_url: str, timeout_seconds: int) -> None:
        self.model = model
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    def choose_tool(
        self, context: dict[str, Any], tools: list[dict[str, Any]]
    ) -> AgentDecision:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": (
                    "Choose exactly one supplied recovery tool and include a short reason."
                )},
                {"role": "user", "content": json.dumps(context, sort_keys=True)},
            ],
            "tools": [{"type": "function", "function": tool} for tool in tools],
            "options": {"temperature": 0},
        }
        request = urllib.request.Request(
            self.base_url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = json.load(response)
            message = raw["message"]
            calls = tuple(
                ToolCall(item["function"]["name"], dict(item["function"]["arguments"]))
                for item in message.get("tool_calls", [])
            )
            rationale = (message.get("content") or "").strip()
            if not rationale and calls:
                rationale = str(calls[0].arguments.get("reason", "Tool selected by Ollama."))
            return AgentDecision(self.provider, self.model, rationale, calls)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise LLMProviderError(f"Ollama request failed or returned invalid data: {error}") from error
