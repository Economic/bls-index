"""scripts/publish.sh against a fake `gh`: the release stays a draft until its digests match."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish.sh"
FAKE_GH = ROOT / "tests" / "harness" / "fake_gh.py"
REPO = "Economic/bls-index"
TAG = "catalog-2026-10-21T0917Z"


@pytest.fixture
def gh(tmp_path):
    """A `gh` on PATH that records calls, plus a run directory to publish."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE_GH} \"$@\"\n")
    (bin_dir / "gh").chmod(0o755)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "bls_index.parquet").write_bytes(b"catalog bytes")
    (run_dir / "latest.json").write_text(json.dumps({"built_at": "2026-10-21T09:17:42Z"}))

    class Gh:
        state = tmp_path / "state.json"
        log = tmp_path / "calls.jsonl"

        def seed(self, *releases, latest=None):
            entries = [dict(id=i, tag_name=t, draft=d, prerelease=p, created_at=f"2026-09-{i:02d}", assets=[])
                       for i, (t, d, p) in enumerate(releases, start=1)]
            self.state.write_text(json.dumps({"releases": entries, "latest": latest,
                                              "next_id": len(entries) + 1}))

        def run(self, tag=TAG, **switches):
            env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}",
                                "FAKE_GH_STATE": str(self.state), "FAKE_GH_LOG": str(self.log)}
            env |= {f"FAKE_GH_{key.upper()}": "1" for key, on in switches.items() if on}
            return subprocess.run(["bash", str(SCRIPT), str(run_dir), tag, "abc123", REPO],
                                  env=env, capture_output=True, text=True, check=False)

        def calls(self):
            return [json.loads(line) for line in self.log.read_text().splitlines()]

        def releases(self):
            return json.loads(self.state.read_text())

    return Gh()


def published(gh) -> list[list[str]]:
    return [c for c in gh.calls() if c[:3] == ["api", "-X", "PATCH"]]


def test_matching_digests_publish_the_draft_as_latest(gh):
    result = gh.run()
    assert result.returncode == 0, result.stderr
    state = gh.releases()
    (release,) = state["releases"]
    assert release["tag_name"] == TAG and release["draft"] is False and release["prerelease"] is False
    assert state["latest"] == TAG
    create = next(c for c in gh.calls() if c[:2] == ["release", "create"])
    assert "--draft" in create and create[create.index("--target") + 1] == "abc123"


def test_a_wrong_digest_never_publishes_and_deletes_the_draft(gh):
    result = gh.run(bad_digest=True)
    assert result.returncode == 1
    assert "does not match" in result.stderr
    assert published(gh) == []
    assert gh.releases()["releases"] == [] and gh.releases()["latest"] is None


def test_leftover_drafts_and_test_releases_are_deleted_but_not_others(gh):
    gh.seed(("catalog-2026-10-01T0900Z", True, False), ("test-2026-10-02T0900Z", False, True),
            ("v1.0", True, False), ("catalog-2026-09-30T0900Z", False, False),
            latest="catalog-2026-09-30T0900Z")
    assert gh.run().returncode == 0
    tags = {r["tag_name"] for r in gh.releases()["releases"]}
    assert tags == {"v1.0", "catalog-2026-09-30T0900Z", TAG}


def test_a_test_run_publishes_a_prerelease_that_is_not_latest(gh):
    gh.seed(*[(f"catalog-2026-09-{d:02d}T0900Z", False, False) for d in range(1, 15)],
            latest="catalog-2026-09-14T0900Z")
    result = gh.run(tag="test-2026-10-21T0917Z")
    assert result.returncode == 0, result.stderr
    state = gh.releases()
    test = next(r for r in state["releases"] if r["tag_name"] == "test-2026-10-21T0917Z")
    assert test["prerelease"] is True and test["draft"] is False
    assert state["latest"] == "catalog-2026-09-14T0900Z"
    assert len(state["releases"]) == 15  # a test run skips retention


def test_retention_keeps_the_newest_12_catalog_releases(gh):
    gh.seed(*[(f"catalog-2026-09-{d:02d}T0900Z", False, False) for d in range(1, 14)])
    assert gh.run().returncode == 0
    tags = sorted(r["tag_name"] for r in gh.releases()["releases"])
    assert len(tags) == 12 and TAG in tags
    assert "catalog-2026-09-01T0900Z" not in tags and "catalog-2026-09-02T0900Z" not in tags


def test_retention_sorts_by_tag_when_releases_share_a_commit_date(gh):
    # GitHub's created_at is the target commit's date, so weekly releases built from
    # the same commit all share it.
    gh.seed(*[(f"catalog-2026-{m:02d}-01T0900Z", False, False) for m in range(1, 10)]
            + [(f"catalog-2026-{m:02d}-15T0900Z", False, False) for m in range(1, 5)])
    state = gh.releases()
    for release in state["releases"]:
        release["created_at"] = "2026-01-01"
    gh.state.write_text(json.dumps(state))
    assert gh.run().returncode == 0
    tags = sorted(r["tag_name"] for r in gh.releases()["releases"])
    assert len(tags) == 12 and TAG in tags
    assert tags[0] == "catalog-2026-02-01T0900Z"  # the two oldest were deleted


def test_a_lost_publish_response_is_success_if_the_release_is_published(gh):
    result = gh.run(lose_publish=True)
    assert result.returncode == 0, result.stderr
    assert "response was lost" in result.stdout
    assert gh.releases()["latest"] == TAG


def test_a_failed_publish_deletes_the_draft(gh):
    result = gh.run(fail_publish=True)
    assert result.returncode == 1
    assert gh.releases()["releases"] == []


def test_a_failed_retention_deletion_only_warns(gh, tmp_path):
    gh.seed(*[(f"catalog-2026-09-{d:02d}T0900Z", False, False) for d in range(1, 14)])
    result = gh.run(fail_delete=True)
    assert result.returncode == 0, result.stderr
    assert "::warning::Could not delete old release" in result.stdout
    assert gh.releases()["latest"] == TAG
