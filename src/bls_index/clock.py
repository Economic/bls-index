"""Injectable UTC clock. All workflow time comes from a ``Clock``, never ``datetime.now``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as a timezone-aware UTC datetime."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def require_utc(value: datetime) -> datetime:
    """Return ``value`` if it is timezone-aware with a zero UTC offset; raise otherwise."""
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"expected a timezone-aware UTC datetime, got {value!r}")
    return value


def isoformat_utc(value: datetime) -> str:
    """Serialize a UTC datetime with microseconds and a ``Z`` suffix."""
    return require_utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
