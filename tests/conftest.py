from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bls_index.events import EventLog
from tests.harness.clock import FakeClock
from tests.harness.notifier import FakeNotifier


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 1, 12, 0, tzinfo=UTC))


@pytest.fixture
def events(clock: FakeClock) -> EventLog:
    return EventLog(clock)


@pytest.fixture
def notifier() -> FakeNotifier:
    return FakeNotifier()
