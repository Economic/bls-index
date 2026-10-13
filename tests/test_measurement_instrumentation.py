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
        assert source.request_attempts == 2 * len(input_files("pr"))
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
        assert source.request_attempts == 1 + 2 * len(input_files("pr"))
        assert len(http_server.requests) == source.request_attempts
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
