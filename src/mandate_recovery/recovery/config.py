"""Recovery-agent and paired-simulation configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_RECOVERY_CONFIG = Path(__file__).resolve().parents[3] / "config" / "recovery.toml"


@dataclass(frozen=True)
class RecoveryConfig:
    default_provider: str
    max_immediate_turns: int
    retry_cap: int
    recovery_window_days: int
    groq_model: str
    groq_base_url: str
    groq_timeout_seconds: int
    ollama_model: str
    ollama_base_url: str
    ollama_timeout_seconds: int
    compliant_success_probability: Mapping[str, float]
    naive_success_probability: Mapping[str, float]


def load_recovery_config(path: Path = DEFAULT_RECOVERY_CONFIG) -> RecoveryConfig:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    agent, groq, ollama = raw["agent"], raw["groq"], raw["ollama"]
    config = RecoveryConfig(
        default_provider=str(agent["default_provider"]),
        max_immediate_turns=int(agent["max_immediate_turns"]),
        retry_cap=int(agent["retry_cap"]),
        recovery_window_days=int(agent["recovery_window_days"]),
        groq_model=str(groq["model"]),
        groq_base_url=str(groq["base_url"]),
        groq_timeout_seconds=int(groq["timeout_seconds"]),
        ollama_model=str(ollama["model"]),
        ollama_base_url=str(ollama["base_url"]),
        ollama_timeout_seconds=int(ollama["timeout_seconds"]),
        compliant_success_probability=dict(raw["compliant_success_probability"]),
        naive_success_probability=dict(raw["naive_success_probability"]),
    )
    if config.retry_cap < 1 or config.max_immediate_turns < 1:
        raise ValueError("agent caps must be positive")
    for probabilities in (
        config.compliant_success_probability, config.naive_success_probability
    ):
        if any(not 0 <= value <= 1 for value in probabilities.values()):
            raise ValueError("success probabilities must be between 0 and 1")
    return config
