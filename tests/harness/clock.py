"""Deterministic UTC clock for tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from bls_index.clock import require_utc

# Smallest step datetime can represent; "one clock tick" in boundary tests.
TICK = timedelta(microseconds=1)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self._now = require_utc(start)

    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> None:
        self._now = require_utc(value)

    def advance(self, delta: timedelta) -> datetime:
        if delta < timedelta(0):
            raise ValueError("FakeClock cannot move backwards")
        self._now += delta
        return self._now
