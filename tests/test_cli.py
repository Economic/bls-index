"""The ``bls-index build`` command against the local fixture server."""

from __future__ import annotations

import json
import shutil
import subprocess

import polars as pl
import pytest

from bls_index.cli import main
from tests.conftest import TEST_USER_AGENT, TWO_PROGRAM
from tests.harness.http_source import Reply


def _build(http_server, tmp_path, monkeypatch, programs="ap,pr") -> int:
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    return main(["build", "--programs", programs, "--base-url", http_server.base_url,
                 "--workdir", str(tmp_path / "runs"), "--min-request-interval", "0"])


def _report(tmp_path) -> dict:
    (run_dir,) = (tmp_path / "runs").glob("build-*")
    return json.loads((run_dir / "report.json").read_text())


def test_installed_command_runs():
    exe = shutil.which("bls-index")
    assert exe, "bls-index not on PATH; run through `uv run`"
    result = subprocess.run([exe, "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0 and "build" in result.stdout


@pytest.mark.parametrize("programs", ["zz", "ap,ap", ",", "nw"])
def test_build_rejects_programs_outside_initial_scope(programs, tmp_path):
    with pytest.raises(SystemExit) as info:
        main(["build", "--programs", programs, "--workdir", str(tmp_path)])
    assert info.value.code == 2


def test_build_refuses_fast_requests_against_bls(tmp_path, monkeypatch):
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    with pytest.raises(SystemExit) as info:
        main(["build", "--programs", "ap", "--min-request-interval", "0", "--workdir", str(tmp_path)])
    assert info.value.code == 2


def test_build_writes_catalog_and_report(http_server, tmp_path, monkeypatch):
    http_server.serve_tree(TWO_PROGRAM)
    assert _build(http_server, tmp_path, monkeypatch) == 0

    report = _report(tmp_path)
    (run_dir,) = (tmp_path / "runs").glob("build-*")
    catalog = pl.read_parquet(run_dir / "bls_index.parquet")
    assert report["status"] == "success" and report["failure"] is None
    assert [item["status"] for item in report["programs"]] == ["built", "built"]
    source = report["programs"][1]["sources"][0]
    assert (source["file"], source["bytes"]) == ("pr.series", (TWO_PROGRAM / "pr" / "pr.series").stat().st_size)
    assert report["catalog"]["rows"] == catalog.height == sum(i["rows"] for i in report["programs"])
    assert set(catalog["program"]) == {"ap", "pr"}
    assert TEST_USER_AGENT not in (run_dir / "report.json").read_text()


def test_failed_download_stops_the_run_without_a_catalog(http_server, tmp_path, monkeypatch):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("ap/ap.series", Reply(status=404))
    assert _build(http_server, tmp_path, monkeypatch) == 1

    report = _report(tmp_path)
    assert report["status"] == "failed" and report["catalog"] is None
    assert report["failure"]["program"] == "ap" and report["failure"]["stage"] == "download"
    assert [item["program"] for item in report["programs"]] == ["ap"]
    assert not list((tmp_path / "runs").glob("build-*/bls_index.parquet"))


def test_failed_parse_is_reported_as_a_build_failure(http_server, tmp_path, monkeypatch):
    http_server.serve_tree(TWO_PROGRAM)
    http_server.script("ap/ap.series", Reply(body=b"series_id\tseries_title\nAPU1\t \n"))
    assert _build(http_server, tmp_path, monkeypatch, programs="ap") == 1
    assert _report(tmp_path)["failure"]["stage"] == "build"


def test_builder_warnings_are_recorded_per_program(http_server, tmp_path, monkeypatch):
    http_server.serve_tree(TWO_PROGRAM)
    lines = (TWO_PROGRAM / "ap" / "ap.series").read_text().splitlines()
    header = lines[0].replace("series_id", "series_id\tseasonal", 1)
    rows = [line.replace("\t", "\tX\t", 1) for line in lines[1:]]
    http_server.script("ap/ap.series", Reply(body=("\n".join([header, *rows]) + "\n").encode()))
    assert _build(http_server, tmp_path, monkeypatch, programs="ap") == 0
    assert "seasonal code" in _report(tmp_path)["programs"][0]["warnings"][0]


def test_each_run_gets_its_own_directory(http_server, tmp_path, monkeypatch):
    http_server.serve_tree(TWO_PROGRAM)
    assert _build(http_server, tmp_path, monkeypatch, programs="ap") == 0
    assert _build(http_server, tmp_path, monkeypatch, programs="ap") == 0
    assert len(list((tmp_path / "runs").glob("build-*"))) == 2
