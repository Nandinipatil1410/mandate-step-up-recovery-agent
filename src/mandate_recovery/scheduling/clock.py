"""Clock abstraction keeps lifecycle tests instantaneous and deterministic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SimulatedClock:
    current: datetime

    def now(self) -> datetime:
        return self.current

    def advance_to(self, value: datetime) -> None:
        if value < self.current:
            raise ValueError("simulated clock cannot move backwards")
        self.current = value
