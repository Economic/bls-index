"""The installed ``bls-index`` command and its argument handling."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from bls_index.cli import main
from tests.conftest import TEST_USER_AGENT, TWO_PROGRAM
from tests.harness.http_source import Reply


def test_installed_command_runs():
    exe = shutil.which("bls-index")
    assert exe, "bls-index not on PATH; run through `uv run`"
    result = subprocess.run([exe, "runner-info"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["cpu_count"] >= 1


@pytest.mark.parametrize("programs", ["zz", "ap,ap", ",", "nw"])
def test_probe_rejects_programs_outside_initial_scope(programs, tmp_path):
    with pytest.raises(SystemExit) as info:
        main(["probe", "--programs", programs, "--out", str(tmp_path / "r.json")])
    assert info.value.code == 2


def test_keep_files_requires_workdir(tmp_path):
    with pytest.raises(SystemExit) as info:
        main(["probe", "--programs", "ap", "--keep-files", "--out", str(tmp_path / "r.json")])
    assert info.value.code == 2


def run_cli(http_server, tmp_path, monkeypatch, *extra: str) -> int:
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    return main([
        "probe", "--base-url", http_server.base_url, "--out", str(tmp_path / "out" / "r.json"),
        "--events", str(tmp_path / "logs" / "events.jsonl"), "--min-request-interval", "0",
        *extra,
    ])  # fmt: skip


def test_probe_writes_report_and_events_into_new_directories(http_server, tmp_path, monkeypatch):
    http_server.serve_tree(TWO_PROGRAM)
    assert run_cli(http_server, tmp_path, monkeypatch, "--programs", "ap,pr") == 0

    report = json.loads((tmp_path / "out" / "r.json").read_text())
    assert report["summary"]["programs_ok"] == 2
    assert (tmp_path / "logs" / "events.jsonl").read_text().count("\n") > 0


def test_probe_exits_nonzero_on_failed_program(http_server, tmp_path, monkeypatch):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("ap/ap.series", Reply(status=404))
    assert run_cli(http_server, tmp_path, monkeypatch, "--programs", "ap") == 1


def test_probe_outputs_never_contain_the_user_agent(http_server, tmp_path, monkeypatch):
    """CI uploads the report and event log as artifacts; the agent is a repository secret.
    One program fails so failure details are written too."""
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("ap/ap.series", Reply(status=404))
    assert run_cli(http_server, tmp_path, monkeypatch, "--programs", "ap,pr") == 1

    for path in (tmp_path / "out" / "r.json", tmp_path / "logs" / "events.jsonl"):
        text = path.read_text()
        assert TEST_USER_AGENT not in text and "example.invalid" not in text, path


def test_probe_exits_nonzero_on_failed_parse_check(http_server, tmp_path, monkeypatch):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("ap/ap.series", Reply(body=b"series_id\tt\r\nAPU1\tT\tx\r\n"))
    assert run_cli(http_server, tmp_path, monkeypatch, "--programs", "ap", "--parse-check") == 1


def test_dry_build_writes_local_candidate_and_structured_report(http_server, tmp_path, monkeypatch):
    http_server.serve_tree(TWO_PROGRAM)
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    assert main([
        "dry-build", "--programs", "ap,pr", "--base-url", http_server.base_url,
        "--workdir", str(tmp_path / "runs"), "--min-request-interval", "0",
    ]) == 0

    run_dirs = list((tmp_path / "runs").glob("dry-build-*"))
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    report = json.loads((run_dir / "report.json").read_text())
    candidate = run_dir / "combined" / "bls_index.parquet"
    assert report["status"] == "success"
    assert report["scope_complete"] is True
    assert report["requested_programs"] == ["ap", "pr"]
    assert [item["status"] for item in report["programs"]] == ["built", "built"]
    assert report["programs"][0]["sources"][0]["sha256"]
    assert report["programs"][1]["source_total_bytes"] > 0
    assert report["combined"]["sha256"]
    assert report["combined"]["row_count"] > 0
    peak_rss = report["runtime_environment"]["peak_rss"]
    assert peak_rss["self"]["bytes"] >= 0
    assert peak_rss["children"]["bytes"] >= 0
    assert peak_rss["self"]["unit"] == peak_rss["children"]["unit"]
    assert "not a concurrent aggregate" in peak_rss["children"]["scope"]
    assert {item["name"] for item in report["search_queries"]} == {
        "row_count", "distinct_programs", "prefix_lookup_ap", "title_contains_employment"
    }
    assert {"validate-spec", "validate-meta", "validate-data"} == set(
        report["dictionary_check_seconds"]
    )
    assert candidate.is_file()
    assert (run_dir / "events.jsonl").read_text().count("\n") > 0
    assert TEST_USER_AGENT not in (run_dir / "events.jsonl").read_text()
    assert (run_dir / "downloads" / "ap" / "attempt-1" / "read-1" / "ap.series").is_file()

    # Each invocation owns a separate directory and cannot overwrite the first report.
    previous_report = (run_dir / "report.json").read_bytes()
    assert main([
        "dry-build", "--programs", "ap", "--base-url", http_server.base_url,
        "--workdir", str(tmp_path / "runs"), "--min-request-interval", "0",
    ]) == 0
    assert (run_dir / "report.json").read_bytes() == previous_report
    assert len(list((tmp_path / "runs").glob("dry-build-*"))) == 2


def test_dry_build_reports_corrupt_bundle_reload_as_combined_failure(
    http_server, tmp_path, monkeypatch,
):
    from bls_index import dry_build

    http_server.serve_tree(TWO_PROGRAM)
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    workdir = tmp_path / "runs"
    original_read_parquet = dry_build.pl.read_parquet

    def corrupt_bundle_then_read(path, *args, **kwargs):
        bundle_path = Path(path)
        if "bundles" in bundle_path.parts:
            bundle_path.write_bytes(b"not a valid parquet bundle")
        return original_read_parquet(path, *args, **kwargs)

    monkeypatch.setattr(dry_build.pl, "read_parquet", corrupt_bundle_then_read)
    assert main([
        "dry-build", "--programs", "ap", "--base-url", http_server.base_url,
        "--workdir", str(workdir), "--min-request-interval", "0",
    ]) == 1

    run_dir = next(workdir.glob("dry-build-*"))
    report = json.loads((run_dir / "report.json").read_text())
    assert report["status"] == "failed"
    assert report["failure"]["stage"] == "combined_validation"
    assert report["failure"]["reason"]
    assert report["combined"] is None
    assert not (run_dir / "combined" / "bls_index.parquet").exists()
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    assert any(event["kind"] == "dry_build.combined_failed" for event in events)


def test_dry_build_fails_closed_and_redacts_user_agent(http_server, tmp_path, monkeypatch):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("ap/ap.series", Reply(status=404))
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    workdir = tmp_path / "runs"
    assert main([
        "dry-build", "--programs", "ap,pr", "--base-url", http_server.base_url,
        "--workdir", str(workdir), "--min-request-interval", "0",
    ]) == 1

    run_dir = next(workdir.glob("dry-build-*"))
    report_path = run_dir / "report.json"
    report = json.loads(report_path.read_text())
    assert report["status"] == "failed"
    assert report["scope_complete"] is False
    assert report["combined"] is None
    assert not (run_dir / "combined" / "bls_index.parquet").exists()
    assert report["failure"]["program"] == "ap"
    assert TEST_USER_AGENT not in report_path.read_text()


def test_dry_build_rejects_programs_outside_initial_scope(tmp_path):
    with pytest.raises(SystemExit) as info:
        main(["dry-build", "--programs", "nw", "--workdir", str(tmp_path)])
    assert info.value.code == 2


def test_probe_refuses_fast_requests_against_bls(tmp_path, monkeypatch):
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    with pytest.raises(SystemExit) as info:
        main(["probe", "--programs", "ap", "--min-request-interval", "0",
              "--out", str(tmp_path / "r.json")])  # fmt: skip
    assert info.value.code == 2
