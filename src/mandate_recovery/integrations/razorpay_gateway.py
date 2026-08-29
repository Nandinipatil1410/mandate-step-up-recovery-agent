"""Optional Razorpay test-mode plumbing.

This client creates/fetches real test objects when explicitly configured. It
does not simulate or claim to perform bank-side same-mandate AFA.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any


class RazorpayGatewayError(RuntimeError):
    pass


class RazorpayTestGateway:
    BASE_URL = "https://api.razorpay.com/v1"

    def __init__(self, *, key_id: str | None = None, key_secret: str | None = None,
                 timeout_seconds: int = 30) -> None:
        self.key_id = key_id or os.environ.get("RAZORPAY_KEY_ID")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET")
        self.timeout_seconds = timeout_seconds
        if not self.key_id or not self.key_secret:
            raise RazorpayGatewayError("Razorpay test credentials are not configured")
        if not self.key_id.startswith("rzp_test_"):
            raise RazorpayGatewayError("only rzp_test_ credentials are allowed")

    def fetch_subscription(self, subscription_id: str) -> dict[str, Any]:
        return self._request("GET", f"/subscriptions/{subscription_id}")

    def create_alternate_payment_link(
        self, *, amount_paise: int, currency: str, reference_id: str,
        description: str,
    ) -> dict[str, Any]:
        return self._request("POST", "/payment_links", {
            "amount": amount_paise,
            "currency": currency,
            "reference_id": reference_id,
            "description": description,
            "notes": {"recovery_type": "alternate_method", "simulation": "false"},
        })

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        token = base64.b64encode(f"{self.key_id}:{self.key_secret}".encode()).decode()
        request = urllib.request.Request(
            f"{self.BASE_URL}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.load(response)
            if not isinstance(result, dict):
                raise RazorpayGatewayError("Razorpay returned a non-object response")
            return result
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise RazorpayGatewayError(f"Razorpay test request failed: {error}") from error
