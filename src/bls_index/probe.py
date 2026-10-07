"""Source inventory probe for real BLS inputs.

Fetches each program's input set through the production ``HttpSource`` (full download
plus SHA-256 recheck), then records response metadata, bytes, checksums, the observed
table layout, and optional polars parse cost. It writes nothing to object storage.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from bls_index.clock import Clock, isoformat_utc
from bls_index.http_source import HttpSource, InputSet, InputSetError, redact_user_agent
from bls_index.runner_info import runner_info
from bls_index.scope import LOOKUP_FILES


def inspect_table(path: Path) -> dict[str, Any]:
    """Describe a tab-delimited BLS file's layout without interpreting its values."""
    header: list[str] | None = None
    rows = blank = crlf = lf = non_utf8 = 0
    widths: Counter[int] = Counter()
    padded_first_field = 0
    with path.open("rb") as fh:
        for raw in fh:
            if raw.endswith(b"\r\n"):
                crlf += 1
            elif raw.endswith(b"\n"):
                lf += 1
            line = raw.rstrip(b"\r\n")
            try:
                line.decode("utf-8")
            except UnicodeDecodeError:
                non_utf8 += 1
            fields = line.split(b"\t")
            if header is None:
                header = [f.decode("utf-8", "replace").strip() for f in fields]
                continue
            if not line.strip():
                blank += 1
                continue
            rows += 1
            widths[len(fields)] += 1
            if fields[0] != fields[0].strip():
                padded_first_field += 1
    columns = header or []
    return {
        "header_columns": columns,
        "rows": rows,
        "blank_lines": blank,
        "field_count_histogram": {str(k): v for k, v in sorted(widths.items())},
        "rows_with_header_width": widths.get(len(columns), 0),
        "line_endings": {"crlf": crlf, "lf": lf},
        "non_utf8_lines": non_utf8,
        "padded_first_field_rows": padded_first_field,
    }


def measure_parse(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "-m", "bls_index.parse_probe", str(path)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if proc.returncode != 0:
        return {"ok": False, "returncode": proc.returncode, "error": proc.stderr[-500:]}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"unreadable parse probe output: {proc.stdout[-200:]!r}"}


def lookup_coverage(program: str, series_columns: Sequence[str]) -> dict[str, Any]:
    """Map .series code columns to the configured lookup files (synthesized programs)."""
    lookups = set(LOOKUP_FILES.get(program, ()))
    code_columns = [c for c in series_columns if c.endswith("_code") or c == "seasonal"]
    mapped = {c: c.removesuffix("_code") for c in code_columns}
    return {
        "configured_lookups": sorted(lookups),
        "code_columns": code_columns,
        "code_columns_without_lookup": sorted(c for c, n in mapped.items() if n not in lookups),
        "lookups_without_code_column": sorted(lookups - set(mapped.values())),
    }


def describe_input_set(input_set: InputSet, *, parse_check: bool) -> dict[str, Any]:
    files = []
    for first, recheck in zip(input_set.files, input_set.rechecks, strict=True):
        entry = first.to_json()
        entry["recheck"] = {
            "sha256": recheck.sha256,
            "sha256_match": recheck.sha256 == first.sha256,
            "etag_match": recheck.headers.get("etag") == first.headers.get("etag"),
            "last_modified_match": (
                recheck.headers.get("last-modified") == first.headers.get("last-modified")
            ),
        }
        entry["layout"] = inspect_table(first.path)
        files.append(entry)
    series = files[0]
    result: dict[str, Any] = {
        "ok": True,
        "input_set_attempts": input_set.attempts,
        "files": files,
        "series_rows": series["layout"]["rows"],
        "series_bytes": series["bytes"],
    }
    if input_set.program in LOOKUP_FILES:
        result["lookup_coverage"] = lookup_coverage(
            input_set.program, series["layout"]["header_columns"]
        )
    if parse_check:
        result["parse_check"] = measure_parse(input_set.files[0].path)
    return result


def run_probe(
    programs: Sequence[str],
    source: HttpSource,
    clock: Clock,
    workdir: Path,
    *,
    parse_check: bool = False,
    keep_files: bool = False,
) -> dict[str, Any]:
    """Probe ``programs``. Downloads go to a new run directory created inside
    ``workdir``; only that directory is ever deleted (unless ``keep_files``)."""
    started = clock.now()
    run_dir = Path(tempfile.mkdtemp(prefix="probe-", dir=workdir))
    report: dict[str, Any] = {
        "probe_started_at": isoformat_utc(started),
        "base_url": source.config.base_url,
        # Reports may be published as CI artifacts; never include the contact email.
        "user_agent": redact_user_agent(source.config.user_agent),
        "fetch_config": {
            "connect_timeout": source.config.connect_timeout,
            "read_timeout": source.config.read_timeout,
            "max_request_attempts": source.config.max_request_attempts,
            "max_input_set_attempts": source.config.max_input_set_attempts,
            "max_concurrency": source.config.max_concurrency,
        },
        "runner": runner_info(workdir),
        "programs": {},
    }
    results = source.fetch_programs(programs, run_dir)
    for program, result in results.items():
        if isinstance(result, InputSetError):
            report["programs"][program] = {
                "ok": False,
                "reason": result.reason,
                "attempts": result.attempts,
                "detail": result.detail,
            }
            continue
        report["programs"][program] = describe_input_set(result, parse_check=parse_check)
        if not keep_files:
            shutil.rmtree(run_dir / program, ignore_errors=True)
    if keep_files:
        report["kept_files_dir"] = str(run_dir)
    else:
        shutil.rmtree(run_dir, ignore_errors=True)
    finished = clock.now()
    ok = [p for p, r in report["programs"].items() if r["ok"]]
    report["summary"] = {
        "programs_requested": len(programs),
        "programs_ok": len(ok),
        "programs_failed": sorted(set(programs) - set(ok)),
        "parse_check_failed": sorted(
            p for p in ok
            if "parse_check" in report["programs"][p]
            and not report["programs"][p]["parse_check"].get("ok")
        ),
        "series_rows": sum(report["programs"][p]["series_rows"] for p in ok),
        "downloaded_bytes_once": sum(
            f["bytes"] for p in ok for f in report["programs"][p]["files"]
        ),
        "elapsed_seconds": round((finished - started).total_seconds(), 3),
    }
    report["probe_finished_at"] = isoformat_utc(finished)
    return report
