"""Paired, seeded recovery outcomes for honest strategy comparison."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SimulatedOutcome:
    latent_customer_response: float
    success_probability: float
    recovered: bool
    recovered_amount_paise: int
    time_to_recovery_hours: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "latent_customer_response": self.latent_customer_response,
            "success_probability": self.success_probability,
            "recovered": self.recovered,
            "recovered_amount_paise": self.recovered_amount_paise,
            "time_to_recovery_hours": self.time_to_recovery_hours,
        }


def latent_response(transaction_id: str, seed: int) -> float:
    digest = hashlib.sha256(f"{seed}:{transaction_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def simulate_outcome(
    transaction: dict[str, Any], category: str, probabilities: Mapping[str, float],
    *, seed: int, action_accepted: bool,
) -> SimulatedOutcome:
    latent = latent_response(str(transaction["transaction_id"]), seed)
    probability = float(probabilities[category]) if action_accepted else 0.0
    recovered = latent < probability
    # A stable, synthetic delay from 1 to 72 hours for successful cases.
    delay = round(1 + latent * 71, 2) if recovered else None
    return SimulatedOutcome(
        latent, probability, recovered,
        int(transaction["amount_paise"]) if recovered else 0,
        delay,
    )
