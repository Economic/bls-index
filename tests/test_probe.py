"""The source probe, run through the production fetcher against the fixture server."""

from __future__ import annotations

import json
import subprocess

from pathlib import Path

from bls_index.probe import inspect_table, measure_parse, run_probe
from tests.conftest import TWO_PROGRAM
from tests.harness.http_source import Reply


def test_inspect_table_reports_layout():
    layout = inspect_table(TWO_PROGRAM / "pr" / "pr.series")
    assert layout["header_columns"][:2] == ["series_id", "sector_code"]
    assert layout["rows"] == 8
    assert layout["rows_with_header_width"] == 8
    assert layout["line_endings"] == {"crlf": 9, "lf": 0}
    assert layout["padded_first_field_rows"] == 8

    seasonal = inspect_table(TWO_PROGRAM / "pr" / "pr.seasonal")
    assert seasonal["rows"] == 2 and seasonal["blank_lines"] == 1


def test_probe_reports_inventory_and_failures(http_server, make_source, clock, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("bd/bd.series", Reply(status=404))
    report = run_probe(["ap", "pr", "bd"], make_source(), clock, tmp_path, parse_check=True)

    ap, pr, bd = (report["programs"][p] for p in ("ap", "pr", "bd"))
    assert ap["ok"] and ap["series_rows"] == 6
    assert ap["files"][0]["recheck"]["sha256_match"] is True
    assert ap["parse_check"]["ok"] and ap["parse_check"]["rows"] == 6
    assert pr["lookup_coverage"]["code_columns_without_lookup"] == []
    assert pr["lookup_coverage"]["lookups_without_code_column"] == []
    assert bd == {"ok": False, "reason": "source_error", "attempts": 1,
                  "detail": bd["detail"]}  # fmt: skip
    assert report["summary"]["programs_failed"] == ["bd"]
    assert report["summary"]["parse_check_failed"] == []
    assert report["summary"]["series_rows"] == 14
    assert list(tmp_path.iterdir()) == []  # raw inputs are temporary


def test_probe_reports_schema_drift(http_server, make_source, clock, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script(
        "ap/ap.series", Reply(body=b"series_id\tseries_title\r\nAPU1\tTitle\textra\r\n")
    )
    report = run_probe(["ap"], make_source(), clock, tmp_path)
    layout = report["programs"]["ap"]["files"][0]["layout"]
    assert layout["header_columns"] == ["series_id", "series_title"]
    assert layout["field_count_histogram"] == {"3": 1}
    assert layout["rows_with_header_width"] == 0


def test_probe_never_deletes_files_it_did_not_create(http_server, make_source, clock, tmp_path):
    (tmp_path / "ap").mkdir()
    (tmp_path / "ap" / "notes.txt").write_text("unrelated")
    http_server.serve_tree(TWO_PROGRAM)
    run_probe(["ap"], make_source(), clock, tmp_path)

    assert (tmp_path / "ap" / "notes.txt").read_text() == "unrelated"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ap"]


def test_probe_keep_files_reports_retained_directory(http_server, make_source, clock, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    report = run_probe(["ap"], make_source(), clock, tmp_path, keep_files=True)

    kept = list(Path(report["kept_files_dir"]).rglob("ap.series"))
    assert len(kept) == 1 and kept[0].read_bytes() == (TWO_PROGRAM / "ap" / "ap.series").read_bytes()


def test_parse_check_failure_is_reported(http_server, make_source, clock, tmp_path):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script(
        "ap/ap.series", Reply(body=b"series_id\tseries_title\r\nAPU1\tTitle\textra\r\n")
    )
    report = run_probe(["ap"], make_source(), clock, tmp_path, parse_check=True)

    assert report["programs"]["ap"]["parse_check"]["ok"] is False
    assert report["summary"]["parse_check_failed"] == ["ap"]


def test_killed_parse_subprocess_is_a_failure(monkeypatch, tmp_path):
    killed = subprocess.CompletedProcess(args=[], returncode=-9, stdout="", stderr="Killed")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: killed)
    result = measure_parse(tmp_path / "oe.series")
    assert result["ok"] is False and result["returncode"] == -9


def test_probe_report_never_contains_the_contact_email(http_server, events, clock, tmp_path):
    from bls_index.http_source import FetchConfig, HttpSource

    http_server.serve_tree(TWO_PROGRAM)
    ua = "bls-index test (+https://example.invalid/; ops@example.org)"
    config = FetchConfig(user_agent=ua, base_url=http_server.base_url, min_request_interval=0.0)
    with HttpSource(config, events, clock) as source:
        report = run_probe(["pr"], source, clock, tmp_path)

    assert report["user_agent"] == "bls-index test (+https://example.invalid/; <email>)"
    assert "ops@example.org" not in json.dumps(report)
