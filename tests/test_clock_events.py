"""Injected clock and event log."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from bls_index.clock import SystemClock, isoformat_utc, require_utc
from bls_index.events import EventLog
from tests.harness.clock import TICK, FakeClock

START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def test_fake_clock_rejects_naive_non_utc_and_backwards():
    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 10, 1, 12, 0))
    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 10, 1, 12, 0, tzinfo=timezone(timedelta(hours=-4))))
    clock = FakeClock(START)
    with pytest.raises(ValueError):
        clock.advance(-TICK)


def test_system_clock_is_utc_aware():
    assert require_utc(SystemClock().now())


def test_event_log_uses_injected_clock_and_preserves_order(tmp_path):
    clock = FakeClock(START)
    log = EventLog(clock)
    log.record("a", n=1)
    clock.advance(timedelta(seconds=5))
    log.record("b", n=2)

    assert [(e.seq, e.kind, e.at) for e in log.events] == [
        (0, "a", START), (1, "b", START + timedelta(seconds=5)),
    ]  # fmt: skip
    out = tmp_path / "events.jsonl"
    log.write_jsonl(out)
    lines = out.read_text().splitlines()
    assert '"at": "2026-10-01T12:00:05.000000Z"' in lines[1]
    assert isoformat_utc(START) == "2026-10-01T12:00:00.000000Z"


def test_event_payload_cannot_replace_log_fields(tmp_path):
    clock = FakeClock(START)
    log = EventLog(clock)
    log.record("download", seq=99, at="source time", kind="spoofed")
    out = tmp_path / "events.jsonl"
    log.write_jsonl(out)

    exported = json.loads(out.read_text())
    assert (exported["seq"], exported["at"], exported["kind"]) == (
        0, "2026-10-01T12:00:00.000000Z", "download",
    )  # fmt: skip
    assert exported["data"] == {"seq": 99, "at": "source time", "kind": "spoofed"}


def test_event_payload_is_snapshotted_at_record_time():
    log = EventLog(FakeClock(START))
    headers = {"etag": '"v1"', "sizes": [1, 2]}
    log.record("http.response", headers=headers)
    headers["etag"] = '"v2"'
    headers["sizes"].append(3)

    assert log.events[0].data["headers"] == {"etag": '"v1"', "sizes": [1, 2]}
