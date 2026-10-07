from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bls_index.events import EventLog
from bls_index.http_source import FetchConfig, HttpSource
from tests.harness.clock import FakeClock
from tests.harness.http_source import ControlledHttpSource
from tests.harness.notifier import FakeNotifier

FIXTURES = Path(__file__).parent / "fixtures"
TWO_PROGRAM = FIXTURES / "two_program"
TEST_USER_AGENT = "bls_index test harness (+https://example.invalid/contact)"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 1, 12, 0, tzinfo=UTC))


@pytest.fixture
def events(clock: FakeClock) -> EventLog:
    return EventLog(clock)


@pytest.fixture
def notifier() -> FakeNotifier:
    return FakeNotifier()


@pytest.fixture
def http_server() -> Iterator[ControlledHttpSource]:
    server = ControlledHttpSource().start()
    yield server
    server.stop()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def make_source(http_server, events, clock, sleeps):
    sources: list[HttpSource] = []

    def make(**overrides) -> HttpSource:
        settings = dict(
            user_agent=TEST_USER_AGENT, base_url=http_server.base_url,
            connect_timeout=2.0, read_timeout=0.5, max_request_attempts=3,
            backoff_initial=1.0, backoff_max=8.0, max_input_set_attempts=3,
            max_concurrency=2,
        )  # fmt: skip
        settings.update(overrides)
        source = HttpSource(FetchConfig(**settings), events, clock, sleep=sleeps.append)
        sources.append(source)
        return source

    yield make
    for source in sources:
        source.close()
