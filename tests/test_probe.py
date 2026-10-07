"""The source probe, run through the production fetcher against the fixture server."""

from __future__ import annotations

from bls_index.probe import inspect_table, run_probe
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
    assert report["summary"]["series_rows"] == 14
    assert not (tmp_path / "ap").exists()  # raw inputs are temporary


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
