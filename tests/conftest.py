from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from bls_index.http_source import FetchConfig, HttpSource
from tests.harness.http_source import ControlledHttpSource

FIXTURES = Path(__file__).parent / "fixtures"
TWO_PROGRAM = FIXTURES / "two_program"
TEST_USER_AGENT = "bls_index test harness (+https://example.invalid/contact)"


@pytest.fixture
def http_server() -> Iterator[ControlledHttpSource]:
    server = ControlledHttpSource().start()
    yield server
    server.stop()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def make_source(http_server, sleeps):
    sources: list[HttpSource] = []

    def make(**overrides) -> HttpSource:
        settings = dict(
            user_agent=TEST_USER_AGENT, base_url=http_server.base_url,
            connect_timeout=2.0, read_timeout=0.5, max_attempts=3,
            backoff_initial=1.0, backoff_max=8.0, min_request_interval=0.0,
        )  # fmt: skip
        settings.update(overrides)
        source = HttpSource(FetchConfig(**settings), sleep=sleeps.append)
        sources.append(source)
        return source

    yield make
    for source in sources:
        source.close()
