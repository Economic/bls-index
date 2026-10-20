"""The BLS fetcher against a controlled local HTTP server."""

from __future__ import annotations

import hashlib
from email.utils import format_datetime
from datetime import UTC, datetime, timedelta

import pytest

from bls_index.http_source import DEFAULT_BASE_URL, FetchConfig, HttpSource, SourceError
from bls_index.scope import input_files
from tests.conftest import TEST_USER_AGENT, TWO_PROGRAM
from tests.harness.http_source import Reply

AP_BODY = (TWO_PROGRAM / "ap" / "ap.series").read_bytes()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_each_input_is_downloaded_once_with_checksums(http_server, make_source, tmp_path):
    served = http_server.serve_tree(TWO_PROGRAM)
    downloads = make_source().fetch_program("pr", tmp_path)

    assert list(downloads) == list(input_files("pr"))
    for name, download in downloads.items():
        body = served[f"pr/{name}"]
        assert download.path.read_bytes() == body
        assert (download.bytes, download.sha256) == (len(body), sha(body))
        assert len(http_server.requests_for(f"pr/{name}")) == 1


def test_only_full_unconditional_gets_with_contact_user_agent(http_server, make_source, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    make_source().fetch_program("pr", tmp_path)

    assert http_server.requests
    for request in http_server.requests:
        headers = {k.lower(): v for k, v in request.headers.items()}
        assert request.method == "GET"
        assert headers["user-agent"] == TEST_USER_AGENT
        assert headers["accept-encoding"] == "identity"
        assert not {"if-none-match", "if-modified-since", "if-match", "range"} & set(headers)


@pytest.mark.parametrize("bad", [
    "", "   ", "python-httpx/0.28", "my scraper",
    "bls-index (+https://github.com/Economic/bls-index; a@example.org)",
    "bls-index (+https://economic.GitHub.io/bls-index)",
])  # fmt: skip
def test_user_agent_requires_contact_and_no_github(bad):
    with pytest.raises(ValueError):
        FetchConfig(user_agent=bad)


@pytest.mark.parametrize("status", [403, 404])
def test_client_errors_fail_without_retry(status, http_server, make_source, tmp_path):
    http_server.script("ap/ap.series", Reply(status=status))
    with pytest.raises(SourceError) as info:
        make_source().fetch_program("ap", tmp_path)
    assert info.value.status == status
    assert len(http_server.requests_for("ap/ap.series")) == 1


def test_transient_status_retries_with_backoff_and_retry_after(http_server, make_source, sleeps,
                                                              tmp_path):
    http_server.script("ap/ap.series", Reply(status=503, headers={"Retry-After": "5"}),
                       Reply(status=502), Reply(body=AP_BODY))
    download = make_source().fetch_program("ap", tmp_path)["ap.series"]
    assert download.sha256 == sha(AP_BODY)
    assert sleeps == [5.0, 2.0]  # Retry-After honored, then exponential backoff


def test_retry_after_http_date_is_honored(http_server, make_source, sleeps, tmp_path):
    when = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    http_server.script("ap/ap.series", Reply(status=429, headers={"Retry-After": when}),
                       Reply(body=AP_BODY))
    make_source(backoff_max=60.0).fetch_program("ap", tmp_path)
    assert len(sleeps) == 1 and 25 < sleeps[0] <= 30


def test_retry_after_beyond_limit_stops_instead_of_retrying_early(http_server, make_source, sleeps,
                                                                  tmp_path):
    http_server.script("ap/ap.series", Reply(status=503, headers={"Retry-After": "120"}))
    with pytest.raises(SourceError):
        make_source(backoff_max=60.0).fetch_program("ap", tmp_path)
    assert sleeps == []
    assert len(http_server.requests_for("ap/ap.series")) == 1


def test_retries_are_bounded(http_server, make_source, tmp_path):
    http_server.script("ap/ap.series", Reply(status=503))
    with pytest.raises(SourceError, match="HTTP 503"):
        make_source(max_attempts=3).fetch_program("ap", tmp_path)
    assert len(http_server.requests_for("ap/ap.series")) == 3


@pytest.mark.parametrize("first", [
    Reply(body=AP_BODY, delay=1.0),  # timeout before headers
    Reply(close_without_response=True),
    Reply(body=AP_BODY, truncate_at=40),  # short of Content-Length
    Reply(body=AP_BODY, chunked=True, truncate_at=200),  # missing terminal chunk
], ids=["timeout", "closed", "truncated", "truncated-chunked"])
def test_network_faults_are_retried(first, http_server, make_source, tmp_path):
    http_server.script("ap/ap.series", first, Reply(body=AP_BODY))
    download = make_source(read_timeout=0.2).fetch_program("ap", tmp_path)["ap.series"]
    assert download.path.read_bytes() == AP_BODY
    assert len(http_server.requests_for("ap/ap.series")) == 2


def test_persistent_truncation_fails_as_incomplete(http_server, make_source, tmp_path):
    http_server.script("ap/ap.series", Reply(body=AP_BODY, truncate_at=40))
    with pytest.raises(SourceError) as info:
        make_source().fetch_program("ap", tmp_path)
    assert info.value.reason == "incomplete"


def test_chunked_body_without_content_length_downloads(http_server, make_source, tmp_path):
    """BLS serves most .series files chunked with no Content-Length (probe, 2026-10-07)."""
    http_server.script("ap/ap.series", Reply(body=AP_BODY, chunked=True))
    download = make_source().fetch_program("ap", tmp_path)["ap.series"]
    assert (download.bytes, download.sha256) == (len(AP_BODY), sha(AP_BODY))


def test_unexpected_content_encoding_is_rejected(http_server, make_source, tmp_path):
    http_server.script("ap/ap.series", Reply(body=b"\x1f\x8b", headers={"Content-Encoding": "gzip"}))
    with pytest.raises(SourceError) as info:
        make_source().fetch_program("ap", tmp_path)
    assert info.value.reason == "content_encoding"


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_request_starts_are_spaced_including_retries(http_server, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("pr/pr.series", Reply(status=503), Reply(body=b"x"))
    t = FakeTime()
    config = FetchConfig(user_agent=TEST_USER_AGENT, base_url=http_server.base_url,
                         min_request_interval=1.0, backoff_initial=0.25)
    with HttpSource(config, sleep=t.sleep, monotonic=t.monotonic) as source:
        source.fetch_program("pr", tmp_path)
    # Six requests (the .series retried once); the 0.25 s backoff is topped up to 1 s.
    assert t.slept == [0.25, 0.75, 1.0, 1.0, 1.0, 1.0]


def test_interval_is_measured_from_when_the_server_answers(http_server, tmp_path):
    """A request that is slow to reach the server must not shorten the next gap."""
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("pr/pr.series", Reply(body=b"x", delay=0.3))  # headers 0.3 s late
    config = FetchConfig(user_agent=TEST_USER_AGENT, base_url=http_server.base_url,
                         min_request_interval=0.3)
    with HttpSource(config) as source:
        source.fetch_program("pr", tmp_path)
    arrivals = [request.arrived for request in http_server.requests]
    assert arrivals[1] - arrivals[0] >= 0.55  # 0.3 s to answer, then the 0.3 s interval


@pytest.mark.parametrize("interval", [-1.0, float("nan"), float("inf"), 0.0, 0.5])
def test_bls_requires_at_least_one_second_between_requests(interval):
    with pytest.raises(ValueError):
        FetchConfig(user_agent=TEST_USER_AGENT, base_url=DEFAULT_BASE_URL,
                    min_request_interval=interval)


def test_local_test_sources_may_use_shorter_intervals():
    config = FetchConfig(user_agent=TEST_USER_AGENT, base_url="http://127.0.0.1:8080/pub/",
                         min_request_interval=0.0)
    assert config.min_request_interval == 0.0
