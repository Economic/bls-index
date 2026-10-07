"""Controlled HTTP source and the production fetcher's fault handling."""

from __future__ import annotations

import hashlib

import pytest

import threading
import time

from bls_index.http_source import (
    DEFAULT_BASE_URL,
    FetchConfig,
    InputSetError,
    RequestPacer,
    redact_user_agent,
    validate_user_agent,
)
from bls_index.scope import input_files
from tests.conftest import TEST_USER_AGENT, TWO_PROGRAM
from tests.harness.http_source import Reply

PR_FILES = input_files("pr")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def kinds(events) -> list[str]:
    return [e.kind for e in events.events]


def test_fixture_input_sets_download_and_verify(http_server, make_source, events, tmp_path):
    served = http_server.serve_tree(TWO_PROGRAM)
    source = make_source()

    results = source.fetch_programs(["ap", "pr"], tmp_path)

    for program in ("ap", "pr"):
        result = results[program]
        assert not isinstance(result, InputSetError)
        assert result.attempts == 1
        assert [r.url.removeprefix(http_server.base_url) for r in result.files] == [
            f"{program}/{name}" for name in input_files(program)
        ]
        for record in result.files:
            body = served[record.url.removeprefix(http_server.base_url)]
            assert record.path.read_bytes() == body
            assert (record.sha256, record.bytes, record.status) == (sha(body), len(body), 200)
            assert record.headers["content-length"] == str(len(body))
    # Every input is fetched exactly twice (download + identity recheck).
    for rel in served:
        assert len(http_server.requests_for(rel)) == 2


def test_only_full_unconditional_gets_with_contact_user_agent(http_server, make_source, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    make_source().fetch_input_set("pr", tmp_path)

    assert http_server.requests
    for req in http_server.requests:
        assert req.method == "GET"
        lowered = {k.lower(): v for k, v in req.headers.items()}
        assert lowered["user-agent"] == TEST_USER_AGENT
        assert lowered["accept-encoding"] == "identity"
        for header in ("if-none-match", "if-modified-since", "if-match", "range"):
            assert header not in lowered


@pytest.mark.parametrize(
    "bad",
    [
        "", "   ", "python-httpx/0.28", "my scraper",
        "bls-index (+https://github.com/Economic/bls-index; a@example.org)",
        "bls-index (+https://economic.GitHub.io/bls-index)",
    ],
)  # fmt: skip
def test_user_agent_requires_contact(bad):
    with pytest.raises(ValueError):
        validate_user_agent(bad)
    with pytest.raises(ValueError):
        FetchConfig(user_agent=bad)


@pytest.mark.parametrize("status", [404, 403])
def test_client_error_fails_program_without_retry(status, http_server, make_source, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("pr/pr.class", Reply(status=status))
    source = make_source()

    with pytest.raises(InputSetError) as info:
        source.fetch_input_set("pr", tmp_path)

    assert info.value.reason == "source_error"
    assert info.value.attempts == 1
    assert info.value.source_error.status == status
    assert len(http_server.requests_for("pr/pr.class")) == 1
    assert not (tmp_path / "pr" / "attempt-1").exists()


def test_transient_status_retries_with_backoff(http_server, make_source, sleeps, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    body = (TWO_PROGRAM / "ap" / "ap.series").read_bytes()
    http_server.script(
        "ap/ap.series",
        Reply(status=503, headers={"Retry-After": "5"}),
        Reply(status=502),
        Reply(body=body),
    )
    result = make_source().fetch_input_set("ap", tmp_path)

    assert result.files[0].sha256 == sha(body)
    assert result.files[0].request_attempts == 3
    assert sleeps == [5.0, 2.0]  # Retry-After honored, then exponential backoff


def test_retry_after_http_date_is_honored(http_server, make_source, sleeps, clock, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    body = (TWO_PROGRAM / "ap" / "ap.series").read_bytes()
    # The fake clock reads 2026-10-01 12:00:00 UTC; the server asks for 12:00:30.
    http_server.script(
        "ap/ap.series",
        Reply(status=429, headers={"Retry-After": "Thu, 01 Oct 2026 12:00:30 GMT"}),
        Reply(body=body),
    )
    result = make_source(backoff_max=60.0).fetch_input_set("ap", tmp_path)

    assert result.files[0].request_attempts == 2
    assert sleeps == [30.0]


@pytest.mark.parametrize("retry_after", ["120", "Thu, 01 Oct 2026 12:05:00 GMT"])
def test_retry_after_beyond_limit_stops_instead_of_retrying_early(
    retry_after, http_server, make_source, sleeps, events, tmp_path
):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("ap/ap.series", Reply(status=503, headers={"Retry-After": retry_after}))
    with pytest.raises(InputSetError) as info:
        make_source(backoff_max=60.0).fetch_input_set("ap", tmp_path)

    assert info.value.attempts == 1
    assert len(http_server.requests_for("ap/ap.series")) == 1
    assert sleeps == []
    assert events.of_kind("http.retry_after_exceeds_limit")


def test_recheck_records_carry_no_deleted_paths(http_server, make_source, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    result = make_source().fetch_input_set("pr", tmp_path)

    assert all(r.path is None for r in result.rechecks)
    assert all(r.path is not None and r.path.exists() for r in result.files)
    assert [r.sha256 for r in result.rechecks] == [r.sha256 for r in result.files]


def test_request_retries_are_bounded(http_server, make_source, sleeps, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("ap/ap.series", Reply(status=503))
    with pytest.raises(InputSetError) as info:
        make_source(max_input_set_attempts=2).fetch_input_set("ap", tmp_path)

    assert info.value.reason == "source_error"
    assert info.value.attempts == 2
    # 3 request attempts per input-set attempt.
    assert len(http_server.requests_for("ap/ap.series")) == 6


def test_timeout_before_headers_is_retried(http_server, make_source, events, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    body = (TWO_PROGRAM / "ap" / "ap.series").read_bytes()
    http_server.script("ap/ap.series", Reply(body=body, delay=1.0), Reply(body=body))
    result = make_source(read_timeout=0.2).fetch_input_set("ap", tmp_path)

    assert result.files[0].request_attempts == 2
    retry = events.of_kind("http.retry")[0]
    assert retry.data["reason"] == "timeout"


def test_truncated_body_retries_entire_input_set(http_server, make_source, events, tmp_path):
    served = http_server.serve_tree(TWO_PROGRAM)
    body = served["pr/pr.series"]
    http_server.script("pr/pr.series", Reply(body=body, truncate_at=40), Reply(body=body))
    result = make_source().fetch_input_set("pr", tmp_path)

    assert result.attempts == 2
    failed = events.of_kind("input_set.failed_attempt")
    assert [(e.data["reason"], e.data["attempt"]) for e in failed] == [("incomplete", 1)]
    # The whole set restarts: .series is fetched 1 (truncated) + 2, and every lookup 2
    # times in attempt 2 only (attempt 1 stopped at the first file).
    assert len(http_server.requests_for("pr/pr.series")) == 3
    for name in PR_FILES[1:]:
        assert len(http_server.requests_for(f"pr/{name}")) == 2


def test_chunked_body_without_content_length_downloads(http_server, make_source, tmp_path):
    """BLS serves most .series files chunked with no Content-Length (probe, 2026-10-07)."""
    served = http_server.serve_tree(TWO_PROGRAM)
    body = served["ap/ap.series"]
    http_server.script("ap/ap.series", Reply(body=body, chunked=True))
    record = make_source().fetch_input_set("ap", tmp_path).files[0]

    assert "content-length" not in record.headers
    assert (record.bytes, record.sha256) == (len(body), sha(body))


def test_truncated_chunked_body_is_incomplete(http_server, make_source, events, tmp_path):
    """Without Content-Length, a missing terminal chunk is the only truncation signal."""
    served = http_server.serve_tree(TWO_PROGRAM)
    body = served["ap/ap.series"]
    http_server.script(
        "ap/ap.series",
        Reply(body=body, chunked=True, truncate_at=200),
        Reply(body=body, chunked=True),
    )
    result = make_source().fetch_input_set("ap", tmp_path)

    assert result.attempts == 2
    assert result.files[0].sha256 == sha(body)
    failed = events.of_kind("input_set.failed_attempt")
    assert [e.data["reason"] for e in failed] == ["incomplete"]


def test_series_change_during_build_retries_whole_set(http_server, make_source, events, tmp_path):
    served = http_server.serve_tree(TWO_PROGRAM)
    v1 = served["pr/pr.series"]
    v2 = v1 + b"PRS99999999\t9999\t6\t01\t1\tS\t-\t\t2020\tQ01\t2026\tQ02\r\n"
    # First read sees v1; the recheck and everything after see v2.
    http_server.script("pr/pr.series", Reply(body=v1), Reply(body=v2))
    result = make_source().fetch_input_set("pr", tmp_path)

    assert result.attempts == 2
    assert result.files[0].sha256 == sha(v2)
    changed = events.of_kind("input_set.changed")
    assert len(changed) == 1 and changed[0].data["urls"][0].endswith("pr/pr.series")
    # Lookups were unchanged but still re-downloaded with the whole set.
    for name in PR_FILES:
        assert len(http_server.requests_for(f"pr/{name}")) == 4


def test_lookup_change_during_build_retries_whole_set(http_server, make_source, events, tmp_path):
    served = http_server.serve_tree(TWO_PROGRAM)
    v1 = served["pr/pr.measure"]
    http_server.script("pr/pr.measure", Reply(body=v1), Reply(body=v1 + b"99\tNew\t0\tT\t99\r\n"))
    result = make_source().fetch_input_set("pr", tmp_path)

    assert result.attempts == 2
    assert events.of_kind("input_set.changed")[0].data["urls"][0].endswith("pr/pr.measure")
    assert len(http_server.requests_for("pr/pr.series")) == 4


def test_persistent_change_fails_at_bounded_limit(http_server, make_source, events, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("pr/pr.series", *[Reply(body=f"v{i}".encode()) for i in range(20)])
    with pytest.raises(InputSetError) as info:
        make_source(max_input_set_attempts=3).fetch_input_set("pr", tmp_path)

    assert info.value.reason == "changed_during_build"
    assert info.value.attempts == 3
    assert len(events.of_kind("input_set.changed")) == 3
    assert events.of_kind("input_set.failed")[0].data["attempts"] == 3
    assert not any((tmp_path / "pr").glob("attempt-*"))


def test_connection_closed_without_response_is_transport_error(http_server, make_source, events, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    body = (TWO_PROGRAM / "ap" / "ap.series").read_bytes()
    http_server.script("ap/ap.series", Reply(close_without_response=True), Reply(body=body))
    result = make_source().fetch_input_set("ap", tmp_path)

    assert result.files[0].request_attempts == 2
    assert events.of_kind("http.retry")[0].data["reason"] == "transport"


def test_schema_drift_and_empty_bodies_are_served_verbatim(http_server, make_source, tmp_path):
    """The fetcher records bytes; judging layout belongs to the parsers."""
    http_server.serve_tree(TWO_PROGRAM)
    drifted = b"series_id\tnew_column\tseries_title\r\nAPU1\tx\tTitle\r\n"
    http_server.script("ap/ap.series", Reply(body=drifted))
    http_server.script("pr/pr.class", Reply(body=b""))
    source = make_source()

    assert source.fetch_input_set("ap", tmp_path).files[0].path.read_bytes() == drifted
    pr = source.fetch_input_set("pr", tmp_path)
    assert pr.files[PR_FILES.index("pr.class")].bytes == 0


def test_unexpected_content_encoding_is_rejected(http_server, make_source, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("ap/ap.series", Reply(body=b"\x1f\x8b", headers={"Content-Encoding": "gzip"}))
    with pytest.raises(InputSetError) as info:
        make_source().fetch_input_set("ap", tmp_path)
    assert info.value.source_error.reason == "content_encoding"


def test_concurrency_is_bounded(http_server, make_source, tmp_path):
    programs = ["ap", "bd", "ce", "ci", "cm"]
    for program in programs:
        http_server.script(f"{program}/{program}.series", Reply(body=b"h\r\n", delay=0.1))
    results = make_source(max_concurrency=2).fetch_programs(programs, tmp_path)

    assert all(not isinstance(r, InputSetError) for r in results.values())
    assert list(results) == programs
    assert http_server.max_in_flight == 2


def test_failed_program_does_not_block_others(http_server, make_source, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("ap/ap.series", Reply(status=404))
    results = make_source().fetch_programs(["ap", "pr"], tmp_path)

    assert isinstance(results["ap"], InputSetError)
    assert not isinstance(results["pr"], InputSetError)


def test_fault_scripts_replay_deterministically(http_server, make_source, events, clock, tmp_path):
    """The same script yields the same event sequence on a fresh run."""

    def run(subdir: str) -> list[tuple[str, dict]]:
        http_server.serve_tree(TWO_PROGRAM)
        body = (TWO_PROGRAM / "pr" / "pr.series").read_bytes()
        http_server.script(
            "pr/pr.series", Reply(status=503), Reply(body=body, truncate_at=10),
            Reply(body=body), Reply(body=body + b"x"), Reply(body=body),
        )  # fmt: skip
        start = len(events.events)
        make_source().fetch_input_set("pr", tmp_path / subdir)
        return [
            (e.kind, {k: v for k, v in e.data.items() if k != "files"})
            for e in events.events[start:]
        ]

    assert run("a") == run("b")


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_pacer_spaces_request_starts():
    t = FakeTime()
    pacer = RequestPacer(1.0, monotonic=t.monotonic, sleep=t.sleep)

    assert pacer.wait() == 0.0  # first request starts immediately
    assert pacer.wait() == 1.0
    t.now += 0.25
    assert pacer.wait() == 0.75
    t.now += 5.0  # an idle gap longer than the interval needs no wait
    assert pacer.wait() == 0.0
    assert t.slept == [1.0, 0.75]


def test_pacer_with_zero_interval_never_waits():
    t = FakeTime()
    pacer = RequestPacer(0.0, monotonic=t.monotonic, sleep=t.sleep)
    assert [pacer.wait() for _ in range(5)] == [0.0] * 5
    assert t.slept == []


@pytest.mark.parametrize("interval", [-1.0, float("nan"), float("inf"), 0.0, 0.5])
def test_bls_requires_at_least_one_second_between_requests(interval):
    with pytest.raises(ValueError):
        FetchConfig(user_agent=TEST_USER_AGENT, base_url=DEFAULT_BASE_URL,
                    min_request_interval=interval)  # fmt: skip


@pytest.mark.parametrize("host", ["127.0.0.1:8080", "localhost:9000"])
def test_local_test_sources_may_use_shorter_intervals(host):
    config = FetchConfig(user_agent=TEST_USER_AGENT, base_url=f"http://{host}/pub/",
                         min_request_interval=0.0)  # fmt: skip
    assert config.min_request_interval == 0.0


def test_pacer_measures_from_actual_wake_time_when_a_sleeper_oversleeps():
    t = FakeTime()
    oversleep = [0.5]

    def late_sleep(seconds: float) -> None:
        t.sleep(seconds + (oversleep.pop() if oversleep else 0.0))

    pacer = RequestPacer(1.0, monotonic=t.monotonic, sleep=late_sleep)
    released = []
    for _ in range(3):
        pacer.wait()
        released.append(t.now)
    # The second caller woke 0.5 s late; the third is spaced from that actual time.
    assert released == [100.0, 101.5, 102.5]


def test_default_interval_is_one_second():
    assert FetchConfig(user_agent=TEST_USER_AGENT).min_request_interval == 1.0


def arrival_gaps(http_server) -> list[float]:
    times = sorted(r.arrived for r in http_server.requests)
    return [b - a for a, b in zip(times, times[1:])]


def test_concurrent_workers_never_start_requests_closer_than_interval(
    http_server, make_source, tmp_path
):
    """Four workers fetching many small files still start at most one request per interval."""
    programs = ["ap", "bd", "ce", "ci", "cm", "cu", "cw", "cx"]
    for program in programs:
        http_server.script(f"{program}/{program}.series", Reply(body=b"h\r\n"))
    interval = 0.1
    results = make_source(max_concurrency=4, min_request_interval=interval).fetch_programs(
        programs, tmp_path
    )

    assert all(not isinstance(r, InputSetError) for r in results.values())
    assert len(http_server.requests) == 16  # 8 files, each downloaded twice
    # Unpaced, these requests arrive about 0.25 ms apart. Allow 30 ms of scheduling
    # jitter between a client start and its server arrival on a busy machine.
    assert min(arrival_gaps(http_server)) >= interval - 0.03


def test_retries_are_paced_too(http_server, make_source, events, tmp_path):
    body = (TWO_PROGRAM / "ap" / "ap.series").read_bytes()
    http_server.script("ap/ap.series", Reply(status=503), Reply(body=body))
    make_source(min_request_interval=0.1).fetch_input_set("ap", tmp_path)

    assert len(http_server.requests) == 3  # failed attempt, retry, recheck
    assert min(arrival_gaps(http_server)) >= 0.07
    paced = [e.data["paced_seconds"] for e in events.of_kind("http.request")]
    assert paced[0] == 0.0 and all(p > 0 for p in paced[1:])


def test_late_waking_worker_cannot_be_followed_immediately():
    """Real threads: the first sleeper oversleeps; no two releases may bunch up."""
    interval = 0.1
    first = threading.Event()

    def sleep(seconds: float) -> None:
        extra = 0.0 if first.is_set() else 0.15
        first.set()
        time.sleep(seconds + extra)

    pacer = RequestPacer(interval, sleep=sleep)
    released: list[float] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(3):
            pacer.wait()
            with lock:
                released.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    times = sorted(released)
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert len(times) == 12
    assert min(gaps) >= interval - 0.02


def test_redact_user_agent_masks_emails():
    ua = "bls-index catalog builder (+https://www.epi.org/; someone@example.org)"
    assert redact_user_agent(ua) == "bls-index catalog builder (+https://www.epi.org/; <email>)"
