"""The installed ``bls-index`` command and its argument handling."""

from __future__ import annotations

import json
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


def test_probe_exits_nonzero_on_failed_parse_check(http_server, tmp_path, monkeypatch):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("ap/ap.series", Reply(body=b"series_id\tt\r\nAPU1\tT\tx\r\n"))
    assert run_cli(http_server, tmp_path, monkeypatch, "--programs", "ap", "--parse-check") == 1


def test_probe_refuses_fast_requests_against_bls(tmp_path, monkeypatch):
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    with pytest.raises(SystemExit) as info:
        main(["probe", "--programs", "ap", "--min-request-interval", "0",
              "--out", str(tmp_path / "r.json")])  # fmt: skip
    assert info.value.code == 2
