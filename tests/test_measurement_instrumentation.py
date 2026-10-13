from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bls_index.http_source import DownloadRecord, FetchConfig, HttpSource, InputSet
from bls_index.native_parquet import build_native_parquet
from bls_index.scope import input_files
from bls_index.synthesized_builders import JT_INPUT_NAMES, PR_INPUT_NAMES, SM_INPUT_NAMES
from bls_index.synthesized_parquet import build_synthesized_parquet
from tests.conftest import TEST_USER_AGENT, TWO_PROGRAM
from tests.harness.clock import FakeClock
from tests.harness.http_source import Reply


BUILD_TIME = datetime(2026, 10, 7, 12, 34, 56, 123456, tzinfo=UTC)
SYNTH_FIXTURES = Path(__file__).parent / "fixtures" / "real_synthesized"


def _input_set(tmp_path: Path, program: str, names: tuple[str, ...]) -> InputSet:
    files = []
    rechecks = []
    for name in names:
        if program == "pr":
            fixture_root = Path(__file__).parent / "fixtures" / "two_program" / "pr"
        elif program == "ap":
            fixture_root = Path(__file__).parent / "fixtures" / "native"
        else:
            fixture_root = SYNTH_FIXTURES / program
        source = fixture_root / name
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.read_bytes())
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        url = f"https://download.bls.gov/pub/time.series/{program}/{name}"
        files.append(DownloadRecord(url, path, 200, len(data), digest, {}, BUILD_TIME, BUILD_TIME, 1))
        rechecks.append(DownloadRecord(url, None, 200, len(data), digest, {}, BUILD_TIME, BUILD_TIME, 1))
    return InputSet(program, tuple(files), tuple(rechecks), 1)


def _make_source(http_server, events, clock) -> HttpSource:
    config = FetchConfig(
        user_agent=TEST_USER_AGENT,
        base_url=http_server.base_url,
        connect_timeout=2.0,
        read_timeout=0.5,
        backoff_initial=0.0,
        backoff_max=0.0,
        max_input_set_attempts=3,
        min_request_interval=0.0,
    )
    return HttpSource(config, events, clock, sleep=lambda _: None)


def test_transfer_counters_include_first_reads_and_rechecks(http_server, events, clock, tmp_path):
    served = http_server.serve_tree(TWO_PROGRAM)
    source = _make_source(http_server, events, clock)
    try:
        result = source.fetch_input_set("pr", tmp_path)
        assert result.attempts == 1
        expected_input_bytes = sum(len(served[f"pr/{name}"]) for name in input_files("pr"))
        assert source.received_body_bytes == 2 * expected_input_bytes
        assert source.verification_body_bytes == expected_input_bytes
        assert source.retry_body_bytes == 0
        assert source.request_attempts == 2 * len(input_files("pr"))
        assert source.verification_request_attempts == len(input_files("pr"))
        assert source.request_retry_attempts == 0
        assert source.input_set_retries == 0
        assert len(http_server.requests) == source.request_attempts
    finally:
        source.close()


def test_transfer_counters_include_partial_failed_body_and_retried_set(
    http_server, events, clock, tmp_path
):
    served = http_server.serve_tree(TWO_PROGRAM)
    partial_size = (1 << 20) + 128
    http_server.script(
        "pr/pr.series",
        Reply(body=b"x" * (partial_size + 1), truncate_at=partial_size, chunked=True),
        Reply(body=served["pr/pr.series"]),
    )
    source = _make_source(http_server, events, clock)
    try:
        result = source.fetch_input_set("pr", tmp_path)
        assert result.attempts == 2
        expected_input_bytes = sum(len(served[f"pr/{name}"]) for name in input_files("pr"))
        # HTTPX yielded the complete 1 MiB iter_raw chunk before detecting that the
        # following chunk/terminal marker was missing; the remaining 128 bytes were
        # not observable at the application-body iterator boundary and are not counted.
        yielded_partial_bytes = 1 << 20
        assert source.received_body_bytes == yielded_partial_bytes + 2 * expected_input_bytes
        assert source.verification_body_bytes == expected_input_bytes
        assert source.retry_body_bytes == 2 * expected_input_bytes
        assert source.request_attempts == 1 + 2 * len(input_files("pr"))
        assert source.verification_request_attempts == len(input_files("pr"))
        assert source.request_retry_attempts == 0
        assert source.input_set_retries == 1
        assert len(http_server.requests) == source.request_attempts
    finally:
        source.close()


def test_verification_counters_include_discarded_input_set_rechecks(
    http_server, events, clock, tmp_path
):
    served = http_server.serve_tree(TWO_PROGRAM)
    names = input_files("pr")
    input_bytes = sum(len(served[f"pr/{name}"]) for name in names)
    source = _make_source(http_server, events, clock)
    try:
        source.fetch_input_set("pr", tmp_path / "initial")
        previous = (
            source.received_body_bytes,
            source.verification_body_bytes,
            source.retry_body_bytes,
            source.request_attempts,
            source.verification_request_attempts,
            source.request_retry_attempts,
            source.input_set_retries,
        )

        changed_name = names[0]
        original = served[f"pr/{changed_name}"]
        changed = bytes([original[0] ^ 1]) + original[1:]
        http_server.script(
            f"pr/{changed_name}",
            Reply(body=original),  # first read, attempt 1
            Reply(body=changed),  # changed verification read, attempt 1
            Reply(body=original),  # first read, attempt 2
            Reply(body=original),  # verification read, attempt 2
        )
        result = source.fetch_input_set("pr", tmp_path / "changed")

        assert result.attempts == 2
        assert source.verification_body_bytes - previous[1] == 2 * input_bytes
        assert source.verification_request_attempts - previous[4] == 2 * len(names)
        assert source.retry_body_bytes - previous[2] == 2 * input_bytes
        assert source.input_set_retries - previous[6] == 1
        current = (
            source.received_body_bytes,
            source.verification_body_bytes,
            source.retry_body_bytes,
            source.request_attempts,
            source.verification_request_attempts,
            source.request_retry_attempts,
            source.input_set_retries,
        )
        assert all(after >= before for before, after in zip(previous, current, strict=True))
    finally:
        source.close()


def test_verification_counters_include_request_level_retry(
    http_server, events, clock, tmp_path
):
    served = http_server.serve_tree(TWO_PROGRAM)
    names = input_files("pr")
    input_bytes = sum(len(served[f"pr/{name}"]) for name in names)
    retried_name = names[0]
    http_server.script(
        f"pr/{retried_name}",
        Reply(body=served[f"pr/{retried_name}"]),  # first read
        Reply(status=503),  # failed verification request
        Reply(body=served[f"pr/{retried_name}"]),  # request-level retry
    )
    source = _make_source(http_server, events, clock)
    try:
        result = source.fetch_input_set("pr", tmp_path)
        assert result.attempts == 1
        assert source.verification_body_bytes == input_bytes
        assert source.verification_request_attempts == len(names) + 1
        assert source.request_retry_attempts == 1
        assert source.retry_body_bytes == len(served[f"pr/{retried_name}"])
        assert source.input_set_retries == 0
    finally:
        source.close()


def test_verification_counters_include_partial_failed_recheck_body(
    http_server, events, clock, tmp_path
):
    served = http_server.serve_tree(TWO_PROGRAM)
    names = input_files("pr")
    input_bytes = sum(len(served[f"pr/{name}"]) for name in names)
    failed_name = names[0]
    partial_size = (1 << 20) + 128
    http_server.script(
        f"pr/{failed_name}",
        Reply(body=served[f"pr/{failed_name}"]),  # first read, attempt 1
        Reply(
            body=b"x" * (partial_size + 1),
            truncate_at=partial_size,
            chunked=True,
        ),  # partial verification read; this fails the input-set attempt
        Reply(body=served[f"pr/{failed_name}"]),  # first read, attempt 2
        Reply(body=served[f"pr/{failed_name}"]),  # verification read, attempt 2
    )
    source = _make_source(http_server, events, clock)
    try:
        result = source.fetch_input_set("pr", tmp_path)
        assert result.attempts == 2
        yielded_partial_bytes = 1 << 20
        assert source.verification_body_bytes == input_bytes + yielded_partial_bytes
        assert source.verification_request_attempts == 1 + len(names)
        assert source.retry_body_bytes == 2 * input_bytes
        assert source.request_retry_attempts == 0
        assert source.input_set_retries == 1
    finally:
        source.close()


@pytest.mark.parametrize("program", ["native", "synthesized"])
def test_build_timing_callback_emits_scoped_nonnegative_durations(program, tmp_path):
    if program == "native":
        input_set = _input_set(tmp_path / "inputs", "ap", ("ap.series",))
        build = build_native_parquet
    else:
        input_set = _input_set(tmp_path / "inputs", "sm", SM_INPUT_NAMES)
        build = build_synthesized_parquet

    emitted: list[dict[str, float]] = []
    result = build(
        input_set,
        tmp_path / "output",
        FakeClock(BUILD_TIME),
        timing_callback=emitted.append,
    )

    assert result.row_count > 0
    assert len(emitted) == 1
    assert set(emitted[0]) == {
        "input_validation_seconds",
        "parse_seconds",
        "parquet_staging_seconds",
        "parquet_write_seconds",
    }
    assert all(isinstance(value, float) and value >= 0 for value in emitted[0].values())
