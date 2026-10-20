"""CLI coverage for local dry builds."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import polars as pl
import pytest

from bls_index.cli import main
from bls_index.dry_build import _query_metrics
from tests.conftest import TEST_USER_AGENT, TWO_PROGRAM
from tests.harness.http_source import Reply


def test_installed_command_runs():
    exe = shutil.which("bls-index")
    assert exe, "bls-index not on PATH; run through `uv run`"
    result = subprocess.run([exe, "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "dry-build" in result.stdout


@pytest.mark.parametrize("programs", ["zz", "ap,ap", ",", "nw"])
def test_dry_build_rejects_programs_outside_initial_scope(programs, tmp_path):
    with pytest.raises(SystemExit) as info:
        main(["dry-build", "--programs", programs, "--workdir", str(tmp_path)])
    assert info.value.code == 2


def test_dry_build_refuses_fast_requests_against_bls(tmp_path, monkeypatch):
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    with pytest.raises(SystemExit) as info:
        main(["dry-build", "--programs", "ap", "--min-request-interval", "0",
              "--workdir", str(tmp_path)])  # fmt: skip
    assert info.value.code == 2


@pytest.mark.parametrize("base_url", [
    "https://user:secret@example.invalid/path/",
    "https://user@example.invalid/path/",
    "https://example.invalid/path/?token=secret",
    "https://example.invalid/path/#secret",
    "https://example.invalid/path/?",
    "https://example.invalid/path/#",
])
def test_dry_build_rejects_credential_or_query_bearing_base_url_before_run(
    base_url, tmp_path, monkeypatch,
):
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    with pytest.raises(SystemExit) as info:
        main(["dry-build", "--programs", "ap", "--base-url", base_url,
              "--workdir", str(tmp_path / "runs")])
    assert info.value.code == 2
    assert not (tmp_path / "runs").exists()


def test_dry_build_writes_local_candidate_and_structured_report(http_server, tmp_path, monkeypatch):
    from bls_index import dry_build

    http_server.serve_tree(TWO_PROGRAM)
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    staged_peaks = []

    def sample_temporary_combined_stage(sampler):
        stage_dir = sampler._path / "combined"
        stage_dir.mkdir(exist_ok=True)
        stage = stage_dir / ".bls-index-candidate-test-stage"
        stage.write_bytes(b"x" * 1024 * 1024)
        sampler._sample()
        staged_peaks.append(sampler.peak_run_directory_bytes)
        stage.unlink()

    monkeypatch.setattr(dry_build._DiskSampler, "_run", sample_temporary_combined_stage)
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
    sampled_peak = report["storage"]["sampled_peak"]
    assert sampled_peak["sampling_interval_seconds"] == 0.25
    assert sampled_peak["sample_count"] >= 2
    assert sampled_peak["peak_run_directory_bytes"] >= max(staged_peaks)
    assert sampled_peak["peak_filesystem_used_bytes"] >= 0
    assert sampled_peak["lowest_filesystem_free_bytes"] >= 0
    assert "not an absolute guaranteed maximum" in sampled_peak["measurement"]
    assert not list(run_dir.glob("combined/.bls-index-candidate-test-stage"))
    peak_rss = report["runtime_environment"]["peak_rss"]
    assert peak_rss["self"]["bytes"] >= 0
    assert peak_rss["children"]["bytes"] >= 0
    assert peak_rss["self"]["unit"] == peak_rss["children"]["unit"]
    assert "not a concurrent aggregate" in peak_rss["children"]["scope"]
    assert {item["name"] for item in report["search_queries"]} == {
        "row_count", "distinct_programs", "unemployment_ln_nsa", "registered_nurses_oe_nsa"
    }
    assert report["combined"]["load_seconds"] >= 0
    assert all(item["elapsed_seconds"] >= 0 for item in report["search_queries"])
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


def test_search_queries_apply_program_and_seasonality_filters(tmp_path):
    parquet_path = tmp_path / "query.parquet"
    pl.DataFrame({
        "program": ["ln", "ln", "oe", "oe", "oe", "ap"],
        "series_id": ["LNSA1", "LSA2", "OENSA1", "OESA2", "OENSA3", "AP1"],
        "series_title": [
            "Unemployment rate", "Unemployment level", "Registered nurses",
            "Registered nurses", "Nurse registered", "Unemployment price",
        ],
        "seasonal": ["NSA", "SA", "NSA", "SA", "NSA", "NSA"],
    }).write_parquet(parquet_path)

    load_seconds, metrics = _query_metrics(parquet_path)
    counts = {item["name"]: item["result_count"] for item in metrics}
    assert load_seconds >= 0
    assert counts["unemployment_ln_nsa"] == 1
    assert counts["registered_nurses_oe_nsa"] == 1


@pytest.mark.parametrize("empty_query", [
    "unemployment_ln_nsa", "registered_nurses_oe_nsa",
])
def test_full_initial_scope_requires_representative_search_results(
    empty_query, http_server, tmp_path, monkeypatch,
):
    from bls_index import dry_build

    http_server.serve_tree(TWO_PROGRAM)
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    monkeypatch.setattr(dry_build, "INITIAL_PROGRAMS", ("ap",))
    monkeypatch.setattr(
        dry_build, "_query_metrics",
        lambda _path: (0.0, [
            {"name": "row_count", "elapsed_seconds": 0.0, "result_count": 1},
            {"name": "distinct_programs", "elapsed_seconds": 0.0, "result_count": 1},
            {"name": "unemployment_ln_nsa", "elapsed_seconds": 0.0,
             "result_count": 0 if empty_query == "unemployment_ln_nsa" else 1},
            {"name": "registered_nurses_oe_nsa", "elapsed_seconds": 0.0,
             "result_count": 0 if empty_query == "registered_nurses_oe_nsa" else 1},
        ]),
    )
    workdir = tmp_path / "runs"
    assert main([
        "dry-build", "--programs", "ap", "--base-url", http_server.base_url,
        "--workdir", str(workdir), "--min-request-interval", "0",
    ]) == 1

    run_dir = next(workdir.glob("dry-build-*"))
    report = json.loads((run_dir / "report.json").read_text())
    assert report["status"] == "failed"
    assert report["failure"]["stage"] == "combined_validation"
    assert empty_query in report["failure"]["detail"]
    assert report["combined"] is None
    assert not (run_dir / "combined" / "bls_index.parquet").exists()


def test_dry_build_rejects_changed_valid_bundle_before_reload(http_server, tmp_path, monkeypatch):
    from bls_index import dry_build

    http_server.serve_tree(TWO_PROGRAM)
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    workdir = tmp_path / "runs"
    original_build = dry_build.build_native_parquet
    original_read_parquet = dry_build.pl.read_parquet
    bundle_reads = []

    def alter_bundle_after_build(*args, **kwargs):
        result = original_build(*args, **kwargs)
        frame = original_read_parquet(result.parquet_path)
        frame.with_columns(pl.lit("tampered but valid parquet").alias("series_title")).write_parquet(
            result.parquet_path
        )
        return result

    def count_bundle_reads(path, *args, **kwargs):
        if "bundles" in Path(path).parts:
            bundle_reads.append(Path(path))
        return original_read_parquet(path, *args, **kwargs)

    monkeypatch.setattr(dry_build, "build_native_parquet", alter_bundle_after_build)
    monkeypatch.setattr(dry_build.pl, "read_parquet", count_bundle_reads)
    assert main([
        "dry-build", "--programs", "ap", "--base-url", http_server.base_url,
        "--workdir", str(workdir), "--min-request-interval", "0",
    ]) == 1

    run_dir = next(workdir.glob("dry-build-*"))
    report = json.loads((run_dir / "report.json").read_text())
    assert report["status"] == "failed"
    assert report["failure"]["stage"] == "combined_validation"
    assert "integrity check failed" in report["failure"]["detail"]
    assert report["combined"] is None
    assert not (run_dir / "combined" / "bls_index.parquet").exists()
    assert bundle_reads == []


def test_dry_build_reports_corrupt_bundle_reload_as_combined_failure(
    http_server, tmp_path, monkeypatch,
):
    from bls_index import dry_build

    http_server.serve_tree(TWO_PROGRAM)
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    workdir = tmp_path / "runs"
    original_build = dry_build.build_native_parquet

    def corrupt_bundle_after_build(*args, **kwargs):
        result = original_build(*args, **kwargs)
        result.parquet_path.write_bytes(b"not a valid parquet bundle")
        return result

    monkeypatch.setattr(dry_build, "build_native_parquet", corrupt_bundle_after_build)
    assert main([
        "dry-build", "--programs", "ap", "--base-url", http_server.base_url,
        "--workdir", str(workdir), "--min-request-interval", "0",
    ]) == 1

    run_dir = next(workdir.glob("dry-build-*"))
    report = json.loads((run_dir / "report.json").read_text())
    assert report["status"] == "failed"
    assert report["failure"]["stage"] == "combined_validation"
    assert report["failure"]["reason"] == "ValueError"
    assert "integrity check failed" in report["failure"]["detail"]
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
    assert report["checkpoint"] == "program_failed:ap"


def test_dry_build_download_oserror_is_reported(http_server, tmp_path, monkeypatch):
    from bls_index import dry_build

    http_server.serve_tree(TWO_PROGRAM)
    monkeypatch.setenv("BLS_INDEX_USER_AGENT", TEST_USER_AGENT)
    monkeypatch.setattr(dry_build.HttpSource, "fetch_input_set",
                        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("fixture disk issue")))
    workdir = tmp_path / "runs"
    assert main([
        "dry-build", "--programs", "ap", "--base-url", http_server.base_url,
        "--workdir", str(workdir), "--min-request-interval", "0",
    ]) == 1
    run_dir = next(workdir.glob("dry-build-*"))
    report = json.loads((run_dir / "report.json").read_text())
    assert report["failure"]["stage"] == "download"
    assert report["failure"]["reason"] == "OSError"
