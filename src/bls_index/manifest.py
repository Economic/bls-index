"""The release manifest (`latest.json`) and the weekly publish decision."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bls_index.combined_candidate import CATALOG_NAME
from bls_index.schema import SCHEMA_VERSION
from bls_index.scope import INITIAL_PROGRAMS

MANIFEST_VERSION = 1
MANIFEST_NAME = "latest.json"
PUBLISH_EVERY = timedelta(days=6)


class ManifestError(ValueError):
    pass


def release_tag(built_at: datetime, *, test: bool = False) -> str:
    """`catalog-YYYY-MM-DDTHHMMZ` (or `test-...`) from the build's UTC start time."""
    return f"{'test' if test else 'catalog'}-{built_at.astimezone(UTC):%Y-%m-%dT%H%MZ}"


def write_manifest(run_dir: Path, repo: str, *, test: bool = False,
                   now: datetime | None = None) -> dict[str, Any]:
    """Write `run_dir/latest.json` for a successful full build, and return it.

    Refuses a failed build, a subset build, or a catalog that no longer matches its
    report: only a complete build of the 33 programs in scope may be published.
    """
    run_dir = Path(run_dir)
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    if report.get("status") != "success":
        raise ManifestError(f"build status is {report.get('status')!r}, not 'success'")
    if report.get("requested_programs") != list(INITIAL_PROGRAMS):
        raise ManifestError("build did not cover exactly the programs in scope; a subset "
                            "build is a diagnostic, not a publication")
    catalog = run_dir / CATALOG_NAME
    sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()
    if sha256 != report["catalog"]["sha256"] or catalog.stat().st_size != report["catalog"]["bytes"]:
        raise ManifestError(f"{catalog} does not match the build report")

    built_at = datetime.fromisoformat(report["started_at"])
    tag = release_tag(built_at, test=test)
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "schema_version": SCHEMA_VERSION,
        "tag": tag,
        "built_at": _utc(built_at),
        "published_at": _utc(now or datetime.now(UTC)),
        "git_revision": report.get("git_revision"),
        "catalog": {
            "url": f"https://github.com/{repo}/releases/download/{tag}/{CATALOG_NAME}",
            "sha256": sha256,
            "bytes": catalog.stat().st_size,
            "rows": report["catalog"]["rows"],
        },
        "programs": [
            {
                "program": item["program"],
                "rows": item["rows"],
                "inputs": [{key: source[key] for key in ("file", "bytes", "sha256")}
                           for source in item["sources"]],
            }
            for item in report["programs"]
        ],
    }
    (run_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def publish_due(previous: Path | None, *, now: datetime | None = None) -> bool:
    """True when there is no previous manifest, or its build is at least 6 days old."""
    if previous is None:
        return True
    built_at = json.loads(Path(previous).read_text(encoding="utf-8"))["built_at"]
    age = (now or datetime.now(UTC)) - datetime.fromisoformat(built_at)
    return age >= PUBLISH_EVERY


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
