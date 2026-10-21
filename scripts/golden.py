"""Compare this checkout's builders with a saved dry-build run (plan task 1.0).

Usage: uv run python scripts/golden.py RUN_DIR [PROGRAM ...]

RUN_DIR is a ``build-*`` run, or a legacy ``dry-build-*`` run from before Phase 1. For each
program, this rebuilds rows from the run's downloaded inputs with the current checkout
and compares them with that run's output for the program. Exits 1 on any difference.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import polars as pl

from bls_index.builders import build_program
from bls_index.scope import input_files


def main(run_dir: Path, programs: list[str]) -> int:
    report = json.loads((run_dir / "report.json").read_text())
    entries = {item["program"]: item for item in report["programs"]}
    failed = False
    for program in programs or report["requested_programs"]:
        entry = entries[program]
        if "bundle" in entry:  # legacy dry-build run
            inputs = run_dir / "downloads" / program / f"attempt-{entry['input_set_attempts']}" / "read-1"
            expected = pl.read_parquet(run_dir / entry["bundle"]["parquet_path"])
        else:
            inputs = run_dir / "downloads" / program
            expected = pl.read_parquet(run_dir / "bls_index.parquet").filter(pl.col("program") == program)
        files = {name: inputs / name for name in input_files(program)}
        started = time.perf_counter()
        try:
            actual = build_program(program, files)
        except Exception as exc:
            print(f"{program}: ERROR {type(exc).__name__}: {exc}")
            failed = True
            continue
        seconds = time.perf_counter() - started
        # Catalogs from before a column was added lack it; compare the shared columns.
        actual = actual.select(expected.columns)
        if actual.equals(expected):
            print(f"{program}: ok {actual.height} rows {seconds:.1f}s")
            continue
        failed = True
        print(f"{program}: DIFF rows {actual.height} vs {expected.height}; "
              f"schema equal: {actual.schema == expected.schema}")
        if actual.schema == expected.schema:
            only_new = actual.join(expected, on=actual.columns, how="anti", nulls_equal=True)
            only_old = expected.join(actual, on=actual.columns, how="anti", nulls_equal=True)
            print(f"  only in new: {only_new.height}; only in golden: {only_old.height}")
            print(only_new.head(3))
            print(only_old.head(3))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), sys.argv[2:]))
