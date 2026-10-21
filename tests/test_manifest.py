"""The release manifest and the weekly publish decision."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bls_index.builders import build_program
from bls_index.cli import main
from bls_index.combined_candidate import write_combined_candidate
from bls_index.manifest import ManifestError, publish_due, release_tag, write_manifest
from bls_index.scope import INITIAL_PROGRAMS, NATIVE_TITLE_PROGRAMS, input_files

FIXTURES = Path(__file__).parent / "fixtures"
ROOTS = {program: FIXTURES / "real_native" for program in NATIVE_TITLE_PROGRAMS} | {
    "pr": FIXTURES / "two_program" / "pr",
    "sm": FIXTURES / "real_synthesized" / "sm",
    "jt": FIXTURES / "real_synthesized" / "jt",
}
STARTED = "2026-10-21T09:17:42.123456+00:00"


@pytest.fixture(scope="module")
def full_run(tmp_path_factory) -> Path:
    """A successful 33-program run directory built from the fixtures."""
    run_dir = tmp_path_factory.mktemp("run")
    frames, programs = {}, []
    for program in INITIAL_PROGRAMS:
        files = {name: ROOTS[program] / name for name in input_files(program)}
        frames[program] = build_program(program, files)
        programs.append({
            "program": program, "status": "built", "rows": frames[program].height,
            "sources": [{"file": name, "url": f"https://example.invalid/{name}",
                         "bytes": path.stat().st_size,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                        for name, path in files.items()],
        })
    combined = write_combined_candidate(frames, INITIAL_PROGRAMS, run_dir)
    catalog = run_dir / "bls_index.parquet"
    report = {
        "status": "success", "started_at": STARTED, "git_revision": "abc123",
        "requested_programs": list(INITIAL_PROGRAMS), "programs": programs,
        "catalog": {"path": "bls_index.parquet", "rows": combined.height,
                    "bytes": catalog.stat().st_size,
                    "sha256": hashlib.sha256(catalog.read_bytes()).hexdigest()},
    }  # fmt: skip
    (run_dir / "report.json").write_text(json.dumps(report))
    return run_dir


def _edit_report(run_dir: Path, tmp_path: Path, **changes) -> Path:
    copy = tmp_path / "run"
    copy.mkdir()
    (copy / "bls_index.parquet").write_bytes((run_dir / "bls_index.parquet").read_bytes())
    report = json.loads((run_dir / "report.json").read_text()) | changes
    (copy / "report.json").write_text(json.dumps(report))
    return copy


def test_manifest_fields_and_catalog_url(full_run):
    now = datetime(2026, 10, 21, 9, 30, tzinfo=UTC)
    manifest = write_manifest(full_run, "Economic/bls-index", now=now)
    assert json.loads((full_run / "latest.json").read_text()) == manifest
    tag = "catalog-2026-10-21T0917Z"
    assert manifest["tag"] == tag
    assert manifest["built_at"] == "2026-10-21T09:17:42Z"
    assert manifest["published_at"] == "2026-10-21T09:30:00Z"
    assert manifest["git_revision"] == "abc123"
    assert manifest["catalog"]["url"] == (
        f"https://github.com/Economic/bls-index/releases/download/{tag}/bls_index.parquet"
    )
    catalog = (full_run / "bls_index.parquet").read_bytes()
    assert manifest["catalog"]["sha256"] == hashlib.sha256(catalog).hexdigest()
    assert manifest["catalog"]["bytes"] == len(catalog)
    assert [p["program"] for p in manifest["programs"]] == list(INITIAL_PROGRAMS)
    assert set(manifest["programs"][0]["inputs"][0]) == {"file", "bytes", "sha256"}


def test_test_runs_get_a_test_tag(full_run):
    assert write_manifest(full_run, "Economic/bls-index", test=True)["tag"] == "test-2026-10-21T0917Z"
    assert release_tag(datetime(2026, 1, 2, 3, 4, tzinfo=UTC)) == "catalog-2026-01-02T0304Z"


@pytest.mark.parametrize(("change", "message"), [
    ({"status": "failed"}, "not 'success'"),
    ({"requested_programs": ["ap", "pr"]}, "subset"),
    ({"catalog": {"rows": 1, "bytes": 1, "sha256": "0" * 64}}, "does not match"),
])
def test_manifest_refuses_failed_subset_or_altered_builds(full_run, tmp_path, change, message):
    with pytest.raises(ManifestError, match=message):
        write_manifest(_edit_report(full_run, tmp_path, **change), "Economic/bls-index")
    assert not (tmp_path / "run" / "latest.json").exists()


def test_publish_due_six_day_boundary(tmp_path):
    previous = tmp_path / "latest.json"
    previous.write_text(json.dumps({"built_at": "2026-10-14T09:17:00Z"}))
    built = datetime(2026, 10, 14, 9, 17, tzinfo=UTC)
    assert publish_due(previous, now=built + timedelta(days=6)) is True
    assert publish_due(previous, now=built + timedelta(days=6) - timedelta(minutes=1)) is False
    assert publish_due(None) is True


def test_cli_prints_outputs_for_the_workflow(full_run, tmp_path, capsys):
    assert main(["manifest", str(full_run), "--repo", "Economic/bls-index"]) == 0
    assert capsys.readouterr().out.strip() == "tag=catalog-2026-10-21T0917Z"
    assert main(["publish-due"]) == 0
    assert capsys.readouterr().out.strip() == "due=true"
    recent = tmp_path / "latest.json"
    recent.write_text(json.dumps({"built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}))
    assert main(["publish-due", str(recent)]) == 0
    assert capsys.readouterr().out.strip() == "due=false"


def test_cli_manifest_fails_on_a_subset_build(full_run, tmp_path, capsys):
    run = _edit_report(full_run, tmp_path, requested_programs=["ap"])
    assert main(["manifest", str(run), "--repo", "Economic/bls-index"]) == 1
    assert "subset" in capsys.readouterr().err
