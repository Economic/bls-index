"""Download, build, and validate the catalog into a new local run directory."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from bls_index.builders import build_program
from bls_index.combined_candidate import CATALOG_NAME, write_combined_candidate
from bls_index.http_source import HttpSource
from bls_index.scope import INITIAL_PROGRAMS

REPORT_VERSION = 1


def run_build(programs: Sequence[str], source: HttpSource, workdir: Path) -> dict[str, Any]:
    """Build ``programs`` into ``workdir/build-<time>-<id>/`` and return the report.

    The run stops at the first failed program. ``bls_index.parquet`` exists in the run
    directory only if every program and the combined checks passed. ``report.json`` is
    written in every case.
    """
    requested = tuple(programs)
    if not requested or len(set(requested)) != len(requested) or set(requested) - set(INITIAL_PROGRAMS):
        raise ValueError("programs must be a nonempty, unique subset of the initial scope")
    started_at = datetime.now(UTC)
    run_dir = Path(workdir) / f"build-{started_at:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True)
    report: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "status": "failed",
        "started_at": started_at.isoformat(),
        "run_directory": str(run_dir),
        "git_revision": _git_revision(),
        "runner": {"python": sys.version.split()[0], "platform": platform.platform(),
                   "cpu_count": os.cpu_count()},
        "requested_programs": list(requested),
        "programs": [],
        "catalog": None,
        "failure": None,
    }
    run_started = time.perf_counter()
    frames: dict[str, pl.DataFrame] = {}
    for program in requested:
        item: dict[str, Any] = {"program": program, "status": "failed"}
        report["programs"].append(item)
        stage = "download"
        step = time.perf_counter()
        warnings = _Warnings()
        try:
            with warnings:
                downloads = source.fetch_program(program, run_dir / "downloads")
                item["sources"] = [{"file": name, "bytes": d.bytes, "sha256": d.sha256}
                                   for name, d in downloads.items()]
                item["download_seconds"] = round(time.perf_counter() - step, 3)
                stage, step = "build", time.perf_counter()
                frame = build_program(program, {name: d.path for name, d in downloads.items()})
            item.update(status="built", rows=frame.height,
                        build_seconds=round(time.perf_counter() - step, 3))
            frames[program] = frame
        except Exception as exc:
            report["failure"] = {"program": program, "stage": stage,
                                 "error": f"{type(exc).__name__}: {exc}"}
            break
        finally:
            if warnings.messages:
                item["warnings"] = warnings.messages

    if report["failure"] is None:
        step = time.perf_counter()
        try:
            combined = write_combined_candidate(frames, requested, run_dir)
            catalog = run_dir / CATALOG_NAME
            report["catalog"] = {"path": CATALOG_NAME, "rows": combined.height,
                                 "bytes": catalog.stat().st_size, "sha256": _sha256(catalog),
                                 "seconds": round(time.perf_counter() - step, 3)}
            report["status"] = "success"
        except Exception as exc:
            report["failure"] = {"stage": "combine", "error": f"{type(exc).__name__}: {exc}"}

    report["finished_at"] = datetime.now(UTC).isoformat()
    report["total_seconds"] = round(time.perf_counter() - run_started, 3)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


class _Warnings(logging.Handler):
    """Collect warning messages logged while building one program."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def __enter__(self) -> None:
        logging.getLogger("bls_index").addHandler(self)

    def __exit__(self, *exc: object) -> None:
        logging.getLogger("bls_index").removeHandler(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _git_revision() -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                                check=False, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None
