"""Hinglish notification drafting with complete prompt/response capture."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class NotificationDraft:
    provider: str
    model: str
    prompt_version: str
    prompt: str
    response: str
    validation_status: str
    purpose: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NotificationProvider(Protocol):
    provider: str
    model: str

    def draft(self, prompt: str, *, purpose: str) -> str: ...


class TemplateNotificationProvider:
    provider = "template"
    model = "hinglish-template-v1"

    MESSAGES = {
        "stepup": (
            "Aapke subscription payment ke liye ek quick approval chahiye. "
            "Existing mandate par approval complete karein; naya mandate create nahi hoga."
        ),
        "alternate_method": (
            "Yeh recurring payment current RuPay card par supported nahi hai. "
            "Please UPI ya kisi doosre card se payment complete karein."
        ),
        "retry_notice": (
            "Payment complete nahi hua. Hum scheduled date par ek bounded retry karenge. "
            "Please account balance ya card details check kar lein."
        ),
        "promise_follow_up": (
            "Aapki promised payment date miss ho gayi hai. Yeh final reminder hai; "
            "please payment complete karein ya support se contact karein."
        ),
        "escalation": (
            "Payment issue automatically resolve nahi ho saka. "
            "Humne case support team ko safely escalate kar diya hai."
        ),
    }

    def draft(self, prompt: str, *, purpose: str) -> str:
        if purpose not in self.MESSAGES:
            raise ValueError(f"unsupported notification purpose: {purpose}")
        return self.MESSAGES[purpose]


class GroqNotificationProvider:
    provider = "groq"

    def __init__(self, *, model: str, base_url: str, timeout_seconds: int,
                 api_key: str | None = None) -> None:
        self.model = model
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is required for Groq notifications")

    def draft(self, prompt: str, *, purpose: str) -> str:
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps({
                "model": self.model, "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": (
                        "Draft one concise, respectful Hinglish payment-recovery message. "
                        "Never request an OTP, PIN, CVV, or full card number."
                    )},
                    {"role": "user", "content": prompt},
                ],
            }).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return str(json.load(response)["choices"][0]["message"]["content"]).strip()
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError) as error:
            raise RuntimeError(f"Groq notification request failed: {error}") from error


class NotificationGenerator:
    PROMPT_VERSION = "notification-v1"
    FORBIDDEN_TERMS = ("share your otp", "send otp", "cvv", "full card number", "pin number")

    def __init__(self, provider: NotificationProvider) -> None:
        self.provider = provider

    def generate(
        self, *, purpose: str, transaction_id: str, amount_paise: int,
        context_reason: str,
    ) -> NotificationDraft:
        prompt = (
            f"Purpose: {purpose}\nTransaction: {transaction_id}\n"
            f"Amount: INR {amount_paise / 100:.2f}\nReason: {context_reason}\n"
            "Explain the required next step without sensitive payment data."
        )
        response = self.provider.draft(prompt, purpose=purpose).strip()
        if not response:
            raise ValueError("notification response must not be empty")
        lowered = response.lower()
        validation = (
            "rejected_sensitive_request"
            if any(term in lowered for term in self.FORBIDDEN_TERMS)
            else "passed"
        )
        return NotificationDraft(
            self.provider.provider, self.provider.model, self.PROMPT_VERSION,
            prompt, response, validation, purpose,
        )
