"""Controlled HTTP source and the production fetcher's fault handling."""

from __future__ import annotations

import hashlib

import pytest

from bls_index.http_source import FetchConfig, InputSetError, validate_user_agent
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


@pytest.mark.parametrize("bad", ["", "   ", "python-httpx/0.28", "my scraper"])
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
