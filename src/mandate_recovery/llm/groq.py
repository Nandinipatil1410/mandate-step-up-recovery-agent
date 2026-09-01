"""Groq free-tier-compatible OpenAI-style tool-calling client."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from mandate_recovery.models import AgentDecision, ToolCall

from .base import LLMProviderError


class GroqDecisionClient:
    provider = "groq"

    def __init__(self, *, model: str, base_url: str, timeout_seconds: int,
                 api_key: str | None = None) -> None:
        self.model = model
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise LLMProviderError("GROQ_API_KEY is required for provider=groq")

    def choose_tool(
        self, context: dict[str, Any], tools: list[dict[str, Any]]
    ) -> AgentDecision:
        payload = {
            "model": self.model,
            "temperature": 0,
            "tool_choice": "required",
            "messages": [
                {"role": "system", "content": (
                    "Choose exactly one supplied recovery tool. Never invent tools. "
                    "Put a short auditable decision summary in the tool's reason argument."
                )},
                {"role": "user", "content": json.dumps(context, sort_keys=True)},
            ],
            "tools": [{"type": "function", "function": tool} for tool in tools],
        }
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "mandate-recovery-buildathon/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            detail = detail.replace(self.api_key, "[redacted]")
            raise LLMProviderError(
                f"Groq request failed with HTTP {error.code}: {detail}"
            ) from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise LLMProviderError(f"Groq request failed: {error}") from error
        try:
            message = raw["choices"][0]["message"]
            calls = tuple(
                ToolCall(item["function"]["name"], json.loads(item["function"]["arguments"]))
                for item in message.get("tool_calls", [])
            )
            rationale = (message.get("content") or "").strip()
            if not rationale and calls:
                rationale = str(calls[0].arguments.get("reason", "Tool selected by Groq."))
            return AgentDecision(self.provider, self.model, rationale, calls)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise LLMProviderError("Groq returned an invalid tool-call response") from error
