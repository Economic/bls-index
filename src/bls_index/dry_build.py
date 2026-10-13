"""Sequential, local-only orchestration for measured BLS catalog dry builds.

The runner has no publication or object-store integration. It downloads and verifies
one program at a time, writes local content-addressed bundles, then reloads every
bundle only after all programs have succeeded before staging the combined candidate.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import resource
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit, urlunsplit

import polars as pl

from bls_index.clock import Clock
from bls_index.combined_candidate import write_combined_candidate
from bls_index.events import EventLog
from bls_index.http_source import HttpSource, InputSet, InputSetError
from bls_index.native_parquet import NativeParquetBuild, build_native_parquet
from bls_index.scope import INITIAL_PROGRAMS, NATIVE_TITLE_PROGRAMS, input_files
from bls_index.synthesized_parquet import (
    SynthesizedParquetBuild,
    build_synthesized_parquet,
)

BuildResult = NativeParquetBuild | SynthesizedParquetBuild


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _memory_bytes(field: str) -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            name, _, rest = line.partition(":")
            if name == field:
                return int(rest.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            check=False, timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _rss_measurement(who: int) -> dict[str, Any]:
    raw = resource.getrusage(who).ru_maxrss
    # getrusage reports KiB on Linux and bytes on macOS. Expose normalized bytes and
    # preserve the source-unit/value so the measurement's platform-specific basis is clear.
    if sys.platform == "darwin":
        value, unit = int(raw), "bytes"
        byte_count = int(raw)
    else:
        value, unit = int(raw), "KiB"
        byte_count = int(raw * 1024)
    return {"value": value, "unit": unit, "bytes": byte_count}


def _peak_rss() -> dict[str, Any]:
    return {
        "self": {
            **_rss_measurement(resource.RUSAGE_SELF),
            "scope": "current Python process; includes earlier process lifetime peak",
        },
        "children": {
            **_rss_measurement(resource.RUSAGE_CHILDREN),
            "scope": "maximum of terminated child processes; not a concurrent aggregate",
        },
    }


def _query_metrics(parquet_path: Path) -> list[dict[str, Any]]:
    queries: tuple[tuple[str, Callable[[pl.DataFrame], pl.DataFrame]], ...] = (
        ("row_count", lambda frame: frame.select(pl.len().alias("count"))),
        (
            "distinct_programs",
            lambda frame: frame.select(pl.col("program").n_unique().alias("count")),
        ),
        (
            "prefix_lookup_ap",
            lambda frame: frame.filter(pl.col("series_id").str.starts_with("AP")),
        ),
        (
            "title_contains_employment",
            lambda frame: frame.filter(
                pl.col("series_title").str.contains("(?i)employment")
            ),
        ),
    )
    output: list[dict[str, Any]] = []
    # Queries operate on one already-loaded DataFrame; elapsed time excludes Parquet read.
    frame = pl.read_parquet(parquet_path)
    for name, query in queries:
        started = time.perf_counter()
        result = query(frame)
        elapsed = time.perf_counter() - started
        count = result.item(0, "count") if name in {"row_count", "distinct_programs"} else result.height
        output.append({"name": name, "elapsed_seconds": elapsed, "result_count": count})
    return output


def run_dry_build(
    programs: Sequence[str],
    source: HttpSource,
    clock: Clock,
    workdir: Path,
    *,
    dictionary_path: Path | None = None,
    events: EventLog | None = None,
) -> dict[str, Any]:
    """Run a sequential verified-download/local-build benchmark in a fresh run directory."""
    events = events or EventLog(clock)
    requested = tuple(programs)
    if not requested or len(requested) != len(set(requested)):
        raise ValueError("requested program scope must be nonempty and unique")
    unknown = sorted(set(requested) - set(INITIAL_PROGRAMS))
    if unknown:
        raise ValueError(f"requested programs outside initial scope: {unknown!r}")

    root = Path(workdir)
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / f"dry-build-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex}"
    run_dir.mkdir(mode=0o700, exist_ok=False)
    downloads_dir = run_dir / "downloads"
    bundles_dir = run_dir / "bundles"
    downloads_dir.mkdir()
    bundles_dir.mkdir()
    disk_before = shutil.disk_usage(run_dir)
    initial_tree_bytes = _tree_bytes(run_dir)
    run_started = time.perf_counter()
    programs_report: list[dict[str, Any]] = []
    build_results: dict[str, BuildResult] = {}
    failure: dict[str, str] | None = None

    events.record("dry_build.started", programs=list(requested), run_directory=str(run_dir))
    for program in requested:
        events.record("dry_build.program_started", program=program)
        item: dict[str, Any] = {
            "program": program,
            "input_files_requested": list(input_files(program)),
            "status": "failed",
        }
        download_started = time.perf_counter()
        try:
            input_set = source.fetch_input_set(program, downloads_dir)
        except InputSetError as exc:
            item["download_seconds"] = time.perf_counter() - download_started
            events.record("dry_build.program_failed", program=program, stage="download",
                          reason=exc.reason, detail=_safe_failure_detail(exc.detail))
            item["failure"] = {"type": type(exc).__name__, "reason": exc.reason, "attempts": exc.attempts,
                                "detail": _safe_failure_detail(exc.detail)}
            programs_report.append(item)
            failure = {"program": program, "stage": "download", "reason": exc.reason,
                       "detail": _safe_failure_detail(exc.detail)}
            break
        item["download_seconds"] = time.perf_counter() - download_started
        item["input_set_attempts"] = input_set.attempts
        item["sources"] = [
            {"url": _safe_url(record.url), "bytes": record.bytes, "sha256": record.sha256,
             "status": record.status, "request_attempts": record.request_attempts}
            for record in input_set.files
        ]
        item["source_total_bytes"] = sum(record.bytes for record in input_set.files)
        item["build_seconds"] = None
        build_started = time.perf_counter()
        try:
            result = (
                build_native_parquet(input_set, bundles_dir, clock)
                if program in NATIVE_TITLE_PROGRAMS
                else build_synthesized_parquet(input_set, bundles_dir, clock)
            )
        except Exception as exc:
            item["build_seconds"] = time.perf_counter() - build_started
            events.record("dry_build.program_failed", program=program, stage="build",
                          reason=type(exc).__name__, detail=_safe_failure_detail(str(exc)))
            item["failure"] = {"type": type(exc).__name__, "detail": _safe_failure_detail(str(exc))}
            programs_report.append(item)
            failure = {"program": program, "stage": "build", "reason": type(exc).__name__,
                       "detail": _safe_failure_detail(str(exc))}
            break
        item["build_seconds"] = time.perf_counter() - build_started
        item["status"] = "built"
        item["row_count"] = result.row_count
        item["bundle"] = {
            "parquet_path": str(result.parquet_path.relative_to(run_dir)),
            "parquet_bytes": result.parquet_bytes,
            "parquet_sha256": result.parquet_sha256,
            "provenance_path": str(result.provenance_path.relative_to(run_dir)),
            "provenance_sha256": result.provenance_sha256,
        }
        programs_report.append(item)
        build_results[program] = result
        events.record("dry_build.program_built", program=program, row_count=result.row_count,
                      parquet_bytes=result.parquet_bytes, parquet_sha256=result.parquet_sha256)

    combined_info: dict[str, Any] | None = None
    dictionary_metrics: dict[str, float] = {}
    combined_seconds: float | None = None
    query_metrics: list[dict[str, Any]] = []
    if failure is None and len(build_results) == len(requested):
        combined_started = time.perf_counter()
        combined_path = run_dir / "combined" / "bls_index.parquet"
        try:
            frames: dict[str, pl.DataFrame] = {}
            for program in requested:
                frames[program] = pl.read_parquet(build_results[program].parquet_path)
            combined = write_combined_candidate(
                frames, requested, combined_path, dictionary_path=dictionary_path,
                timing_callback=lambda check, seconds: dictionary_metrics.__setitem__(check, seconds),
            )
            combined_seconds = time.perf_counter() - combined_started
            query_metrics = _query_metrics(combined_path)
            combined_info = {
                "path": str(combined_path.relative_to(run_dir)),
                "bytes": combined_path.stat().st_size,
                "sha256": _sha256(combined_path),
                "row_count": combined.height,
                "output_tree_bytes": _tree_bytes(run_dir),
            }
        except Exception as exc:
            combined_seconds = time.perf_counter() - combined_started
            events.record("dry_build.combined_failed", reason=type(exc).__name__,
                          detail=_safe_failure_detail(str(exc)))
            failure = {"stage": "combined_validation", "reason": type(exc).__name__,
                       "detail": _safe_failure_detail(str(exc))}
            # Candidate writer is staged/validated before exposing output. If a later query
            # fails, remove the candidate so a failed run never advertises a success artifact.
            if combined_path.exists():
                combined_path.unlink()
            combined_info = None

    disk_after = shutil.disk_usage(run_dir)
    report = {
        "schema_version": 1,
        "workflow": "local_dry_build",
        "status": "success" if failure is None else "failed",
        "requested_programs": list(requested),
        "scope_complete": failure is None and set(build_results) == set(requested),
        "initial_scope_complete": (
            failure is None and set(requested) == set(INITIAL_PROGRAMS)
            and set(build_results) == set(INITIAL_PROGRAMS)
        ),
        "run_directory": str(run_dir),
        "runtime_environment": {
            "python": sys.version.split()[0], "platform": platform.platform(),
            "machine": platform.machine(), "cpu_count": os.cpu_count(),
            "memory_total_bytes": _memory_bytes("MemTotal"),
            "memory_available_bytes": _memory_bytes("MemAvailable"),
            "git_revision": _git_revision(),
            "peak_rss": _peak_rss(),
        },
        "storage": {
            "disk_total_bytes_before": disk_before.total,
            "disk_free_bytes_before": disk_before.free,
            "disk_total_bytes_after": disk_after.total,
            "disk_free_bytes_after": disk_after.free,
            "run_output_bytes": _tree_bytes(run_dir) - initial_tree_bytes,
        },
        "programs": programs_report,
        "summary": {
            "programs_requested": len(requested),
            "programs_built": len(build_results),
            "source_total_bytes": sum(item.get("source_total_bytes", 0) for item in programs_report),
            "download_seconds": sum(item.get("download_seconds", 0) for item in programs_report),
            "build_seconds": sum(item.get("build_seconds", 0) or 0 for item in programs_report),
            "combined_seconds": combined_seconds,
            "total_seconds": time.perf_counter() - run_started,
        },
        "combined": combined_info,
        "dictionary_check_seconds": dictionary_metrics,
        "search_queries": query_metrics,
        "failure": failure,
        "notes": [
            "Peak RSS records getrusage(RUSAGE_SELF) for this Python process and getrusage(RUSAGE_CHILDREN) for terminated child processes, including data-dict commands; child RSS is the maximum child peak, not a concurrent aggregate. Both measurements report the same platform-specific source unit (KiB except bytes on macOS) and normalized bytes; self includes prior process lifetime peak.",
            "Dictionary command timings are wall time around each pinned data-dict subprocess.",
            "Search timings exclude reading the combined Parquet into memory.",
            "Disk availability is filesystem capacity at measurement time, not a reservation or estimate.",
        ],
    }
    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    events.record("dry_build.finished", status=report["status"],
                  programs_built=report["summary"]["programs_built"])
    _write_sanitized_events(events, run_dir / "events.jsonl")
    return report


def _write_sanitized_events(events: EventLog, path: Path) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for event in events.events:
            data = _sanitize_event_value(dict(event.data))
            stream.write(json.dumps({"seq": event.seq, "at": event.at.isoformat(),
                                     "kind": event.kind, "data": data}, sort_keys=True) + "\n")


def _sanitize_event_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_event_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_event_value(item) for item in value]
    if isinstance(value, str):
        return _safe_failure_detail(value)
    return value


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.port:
            host += f":{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except ValueError:
        return "[URL redacted]"


def _safe_failure_detail(detail: str) -> str:
    """Strip request headers/secrets and multiline traceback-like diagnostics from reports."""
    redacted = detail.replace("\r", " ").replace("\n", " ")
    # Source errors include the request URL; strip userinfo and query/fragment values.
    tokens = redacted.split()
    for index, token in enumerate(tokens):
        if token.startswith(("http://", "https://")):
            try:
                parsed = urlsplit(token.rstrip(",;"))
                safe_netloc = parsed.hostname or ""
                if parsed.port:
                    safe_netloc += f":{parsed.port}"
                tokens[index] = urlunsplit((parsed.scheme, safe_netloc, parsed.path, "", ""))
            except ValueError:
                tokens[index] = "[URL redacted]"
    redacted = " ".join(tokens)
    for marker in ("User-Agent", "Authorization", "Cookie"):
        lowered = redacted.lower()
        position = lowered.find(marker.lower())
        if position >= 0:
            redacted = redacted[:position] + f"[{marker} redacted]"
    return redacted[:1000]
