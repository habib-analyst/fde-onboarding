"""Injected clock — every timestamp in the system comes from here."""
from __future__ import annotations

import time
from typing import Callable

ClockFn = Callable[[], float]


def system_clock() -> float:
    return time.time()


class FakeClock:
    """Deterministic manual clock for fixtures and tests."""

    def __init__(self, start: float = 1_704_067_200.0):  # 2024-01-01T00:00:00Z
        self._now = float(start)

    def __call__(self) -> float:
        return self._now

    def set(self, value: float) -> None:
        self._now = float(value)

    def advance(self, seconds: float) -> float:
        self._now += float(seconds)
        return self._now
