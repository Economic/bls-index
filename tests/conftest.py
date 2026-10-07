from __future__ import annotations

import itertools
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bls_index.events import EventLog
from bls_index.http_source import FetchConfig, HttpSource
from bls_index.object_store import S3ObjectStore, make_s3_client
from tests.harness.clock import FakeClock
from tests.harness.http_source import ControlledHttpSource
from tests.harness.notifier import FakeNotifier
from tests.harness.s3 import FaultProxy, backdoor_client, start_moto

FIXTURES = Path(__file__).parent / "fixtures"
TWO_PROGRAM = FIXTURES / "two_program"
TEST_USER_AGENT = "bls_index test harness (+https://example.invalid/contact)"
_bucket_ids = itertools.count()


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


@pytest.fixture(scope="session")
def moto_endpoint() -> Iterator[str]:
    server, endpoint = start_moto()
    yield endpoint
    server.stop()


@pytest.fixture
def fault_proxy(moto_endpoint) -> Iterator[FaultProxy]:
    proxy = FaultProxy(moto_endpoint)
    yield proxy
    proxy.stop()


@pytest.fixture
def backdoor(moto_endpoint):
    return backdoor_client(moto_endpoint)


@pytest.fixture
def bucket(backdoor) -> str:
    name = f"bls-index-test-{next(_bucket_ids)}"
    backdoor.create_bucket(Bucket=name)
    return name


@pytest.fixture
def store(fault_proxy, bucket, events) -> S3ObjectStore:
    client = make_s3_client(
        fault_proxy.url, "testing", "testing", region="us-east-1",
        connect_timeout=2.0, read_timeout=2.0,
    )  # fmt: skip
    return S3ObjectStore(client, bucket, "test-ns/", events)
