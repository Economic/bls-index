"""Local Parquet bundles for verified synthesized-title inputs."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from bls_index.clock import Clock
from bls_index.http_source import InputSet
from bls_index.native_parquet import (
    NativeParquetBuildError,
    TimingCallback,
    _write_parquet_bundle,
)
from bls_index.synthesized_builders import (
    JT_INPUT_NAMES,
    PR_INPUT_NAMES,
    SM_INPUT_NAMES,
    SynthesizedSeriesError,
    _validate_program_input_set,
    parse_jt_input_set,
    parse_pr_input_set,
    parse_sm_input_set,
)


class SynthesizedParquetBuildError(ValueError):
    """A verified synthesized input could not be safely built locally."""


@dataclass(frozen=True)
class SynthesizedParquetBuild:
    """Paths and checksums for one locally completed synthesized-program build."""

    program: str
    row_count: int
    parquet_path: Path
    provenance_path: Path
    parquet_bytes: int
    parquet_sha256: str
    provenance_sha256: str
    source_built_at: str


_PARSERS = {
    "sm": (SM_INPUT_NAMES, parse_sm_input_set),
    "jt": (JT_INPUT_NAMES, parse_jt_input_set),
    "pr": (PR_INPUT_NAMES, parse_pr_input_set),
}


def build_synthesized_parquet(
    input_set: InputSet,
    output_dir: str | Path,
    clock: Clock,
    *,
    timing_callback: TimingCallback | None = None,
) -> SynthesizedParquetBuild:
    """Build a local schema-v1 bundle from one verified SM, JT, or PR ``InputSet``.

    The existing strict parser validates the complete download/recheck set, stages and
    parses exact source snapshots, and checks the downloaded paths after parsing. The
    shared writer then records every input and checks every downloaded file after output
    staging and immediately before publication or bundle reuse. No requests are made.

    If provided, ``timing_callback`` receives elapsed seconds for input validation,
    the parser call (including work internal to that parser), full Parquet bundle
    staging/publication, and the exact ``DataFrame.write_parquet`` call. The write
    duration is included in staging duration; do not sum these overlapping measures.
    """
    program = input_set.program
    parser_info = _PARSERS.get(program)
    if parser_info is None:
        raise SynthesizedParquetBuildError(
            f"unsupported synthesized program {program!r}; supported: {tuple(_PARSERS)!r}"
        )
    names, parser = parser_info
    timings = {
        "input_validation_seconds": 0.0,
        "parse_seconds": 0.0,
        "parquet_staging_seconds": 0.0,
        "parquet_write_seconds": 0.0,
    }
    try:
        validation_started = time.perf_counter()
        records_by_name = _validate_program_input_set(input_set, program, names)
        timings["input_validation_seconds"] = time.perf_counter() - validation_started
        parse_started = time.perf_counter()
        frame = parser(input_set)
        timings["parse_seconds"] = time.perf_counter() - parse_started
        build = _write_parquet_bundle(
            program,
            frame,
            tuple(records_by_name[name] for name in names),
            output_dir,
            clock,
            verify_after_output_staging=True,
            timing_results=timings,
        )
    except (SynthesizedSeriesError, NativeParquetBuildError) as exc:
        raise SynthesizedParquetBuildError(str(exc)) from exc
    if timing_callback is not None:
        timing_callback(dict(timings))
    return SynthesizedParquetBuild(
        build.program,
        build.row_count,
        build.parquet_path,
        build.provenance_path,
        build.parquet_bytes,
        build.parquet_sha256,
        build.provenance_sha256,
        build.source_built_at,
    )
