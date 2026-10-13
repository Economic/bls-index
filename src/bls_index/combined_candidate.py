"""Validate combined schema-v1 candidate frames and write local Parquet candidates.

This module accepts already-built program frames. It performs no downloads and
never updates the repository dictionary or publishes to an external service.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

import polars as pl

from bls_index.native_builders import (
    CANONICAL_SCHEMA,
    SCHEMA_VERSION,
    SERIES_ID_PATTERNS,
)
from bls_index.scope import (
    INITIAL_PROGRAMS,
    NATIVE_TITLE_PROGRAMS,
)


class CombinedCandidateError(ValueError):
    """A set of program frames or a staged candidate violates schema v1."""


_YEAR_LIMIT = 9999
_PERIOD_RE = re.compile(r"^(M(0[1-9]|1[0-3])|Q(0[1-5])|A01)$")
_MONTHLY_PERIOD_RE = re.compile(r"^M(0[1-9]|1[0-3])$")
_SEMIANNUAL_PERIOD_RE = re.compile(r"^S0[1-3]$")
_SEMIANNUAL_PROGRAMS = frozenset({"cu", "cw"})
_SYNTHESIZED_ID_PATTERNS = {
    "sm": r"^[Ss][Mm][SsUu][0-9]{17}$",
    "jt": r"^[Jj][Tt][SsUu][A-Za-z0-9]{18}$",
    "pr": r"^[Pp][Rr][SsUu][0-9]{8}$",
}
_DICTIONARY_NAME = "data-dict.yaml"
_DICTIONARY_SOURCE = "parquet: bls_index.parquet"


def _invalid_rows(frame: pl.DataFrame, predicate: pl.Expr) -> pl.DataFrame:
    return frame.filter(predicate.fill_null(True))


def _validate_frame(frame: pl.DataFrame, program: str) -> None:
    if frame.schema != CANONICAL_SCHEMA:
        raise CombinedCandidateError(
            f"program {program!r} returned schema {frame.schema!r}; "
            f"expected canonical schema v{SCHEMA_VERSION}: {CANONICAL_SCHEMA!r}"
        )
    if frame.is_empty():
        raise CombinedCandidateError(f"program {program!r} returned no candidate rows")

    wrong_program = _invalid_rows(frame, pl.col("program") != program)
    if wrong_program.height:
        values = wrong_program.get_column("program").unique().head(5).to_list()
        raise CombinedCandidateError(
            f"frame keyed as {program!r} contains mismatched program value(s): {values!r}"
        )

    expected_title_source = (
        "native" if program in NATIVE_TITLE_PROGRAMS else "synthesized"
    )
    wrong_title_source = _invalid_rows(
        frame, pl.col("title_source") != expected_title_source
    )
    if wrong_title_source.height:
        values = wrong_title_source.get_column("title_source").unique().head(5).to_list()
        raise CombinedCandidateError(
            f"program {program!r} requires title_source {expected_title_source!r}; "
            f"got {values!r}"
        )

    series_id = pl.col("series_id")
    if program in SERIES_ID_PATTERNS:
        valid_id = series_id.str.to_uppercase().str.contains(SERIES_ID_PATTERNS[program])
    else:
        valid_id = series_id.str.contains(_SYNTHESIZED_ID_PATTERNS[program])
    bad_id = _invalid_rows(
        frame,
        series_id.is_null()
        | (series_id == "")
        | (series_id != series_id.str.strip_chars())
        | ~valid_id,
    )
    if bad_id.height:
        raise CombinedCandidateError(
            f"program {program!r} has a missing, untrimmed, or invalid BLS series_id"
        )

    bad_title = _invalid_rows(
        frame,
        pl.col("series_title").is_null()
        | (pl.col("series_title").str.strip_chars() == ""),
    )
    if bad_title.height:
        raise CombinedCandidateError(
            f"program {program!r} has a missing or whitespace-only series_title"
        )

    bad_seasonal = _invalid_rows(
        frame, ~pl.col("seasonal").is_in(["SA", "NSA", "unknown"])
    )
    if bad_seasonal.height:
        raise CombinedCandidateError(
            f"program {program!r} has a seasonal value outside SA, NSA, unknown"
        )

    seasonal_code = series_id.str.to_uppercase().str.slice(2, 1)
    seasonal_mismatch = _invalid_rows(
        frame,
        ((pl.col("seasonal") == "SA") & (seasonal_code != "S"))
        | ((pl.col("seasonal") == "NSA") & (seasonal_code != "U")),
    )
    if seasonal_mismatch.height:
        raise CombinedCandidateError(
            f"program {program!r} has a series_id seasonal code inconsistent with seasonal"
        )

    for column in ("begin_year", "end_year"):
        bad_year = _invalid_rows(
            frame,
            pl.col(column).is_not_null()
            & ((pl.col(column) < 1) | (pl.col(column) > _YEAR_LIMIT)),
        )
        if bad_year.height:
            raise CombinedCandidateError(
                f"program {program!r} has {column} outside the positive four-digit year range"
            )

    inverted_years = _invalid_rows(
        frame,
        pl.col("begin_year").is_not_null()
        & pl.col("end_year").is_not_null()
        & (pl.col("begin_year") > pl.col("end_year")),
    )
    if inverted_years.height:
        raise CombinedCandidateError(
            f"program {program!r} has begin_year later than end_year"
        )

    end_period = pl.col("end_period")
    if program in _SEMIANNUAL_PROGRAMS:
        valid_period = end_period.str.contains(_MONTHLY_PERIOD_RE.pattern) | end_period.str.contains(
            _SEMIANNUAL_PERIOD_RE.pattern
        )
    else:
        valid_period = end_period.str.contains(_PERIOD_RE.pattern)
    bad_period = _invalid_rows(
        frame,
        (end_period.is_not_null() & ~valid_period).fill_null(False),
    )
    if bad_period.height:
        raise CombinedCandidateError(
            f"program {program!r} has an unsupported BLS end_period code"
        )

    period_without_year = _invalid_rows(
        frame,
        pl.col("end_period").is_not_null() & pl.col("end_year").is_null(),
    )
    if period_without_year.height:
        raise CombinedCandidateError(
            f"program {program!r} has end_period without end_year"
        )


def validate_combined_candidate(
    frames: Mapping[str, pl.DataFrame],
    requested_programs: Sequence[str],
) -> pl.DataFrame:
    """Validate and combine frames for a unique requested subset of initial scope.

    Frames are supplied explicitly by program; every requested program needs one
    nonempty canonical frame. No builder-implementation readiness is inferred.
    """
    programs = tuple(requested_programs)
    if not programs:
        raise CombinedCandidateError("requested program scope must not be empty")
    if len(programs) != len(set(programs)):
        raise CombinedCandidateError("requested program scope contains duplicates")
    unknown = sorted(set(programs) - set(INITIAL_PROGRAMS))
    if unknown:
        raise CombinedCandidateError(f"requested programs outside initial scope: {unknown!r}")
    missing = sorted(set(programs) - set(frames))
    unexpected = sorted(set(frames) - set(programs))
    if missing or unexpected:
        raise CombinedCandidateError(
            f"frame/program scope mismatch; missing frames: {missing!r}; "
            f"unexpected frames: {unexpected!r}"
        )

    validated: list[pl.DataFrame] = []
    for program in programs:
        frame = frames[program]
        _validate_frame(frame, program)
        validated.append(frame)

    combined = pl.concat(validated, how="vertical")
    duplicates = combined.filter(pl.col("series_id").is_duplicated())
    if duplicates.height:
        collisions = (
            duplicates.group_by("series_id")
            .agg(pl.col("program").unique().sort().alias("programs"))
            .sort("series_id")
        )
        collision = collisions.row(0, named=True)
        raise CombinedCandidateError(
            f"series_id collision across combined candidate: {collision['series_id']!r} "
            f"in programs {collision['programs']!r}; this candidate is not accepted "
            "as globally unique"
        )
    return combined.cast(CANONICAL_SCHEMA)


def _run_data_dict_checks(dictionary: Path, repository_root: Path) -> None:
    commands = (
        ("validate-spec",),
        ("validate-meta",),
        ("validate-data",),
    )
    for check in commands:
        result = subprocess.run(
            ["uv", "run", "--locked", "data-dict", *check, str(dictionary), "--json"],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            details = (result.stdout + "\n" + result.stderr).strip()
            raise CombinedCandidateError(
                f"pinned data-dict {check[0]} failed (exit {result.returncode}): {details}"
            )


def write_combined_candidate(
    frames: Mapping[str, pl.DataFrame],
    requested_programs: Sequence[str],
    output_path: str | Path,
    *,
    dictionary_path: str | Path | None = None,
) -> pl.DataFrame:
    """Validate frames and write one compressed Parquet candidate without replacement.

    The candidate is fully staged and checked by the pinned data-dict executable
    before a same-filesystem hard link makes the requested output name visible.
    """
    destination = Path(output_path)
    if destination.exists():
        raise CombinedCandidateError(f"candidate output already exists: {destination}")
    if destination.name != "bls_index.parquet":
        raise CombinedCandidateError(
            "candidate output filename must be the canonical bls_index.parquet"
        )

    combined = validate_combined_candidate(frames, requested_programs)
    root = Path(__file__).resolve().parents[2]
    authoritative_dictionary = (
        Path(dictionary_path) if dictionary_path is not None else root / _DICTIONARY_NAME
    )
    try:
        dictionary_text = authoritative_dictionary.read_text(encoding="utf-8")
    except OSError as exc:
        raise CombinedCandidateError(
            f"cannot read authoritative dictionary {authoritative_dictionary}: {exc}"
        ) from exc
    if dictionary_text.count(_DICTIONARY_SOURCE) != 1:
        raise CombinedCandidateError(
            f"dictionary must contain exactly one {_DICTIONARY_SOURCE!r} source entry"
        )

    made_parent = not destination.parent.exists()
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".bls-index-candidate-", dir=destination.parent
        ) as staging_name:
            staging = Path(staging_name)
            staged_parquet = staging / "bls_index.parquet"
            staged_dictionary = staging / _DICTIONARY_NAME
            combined.write_parquet(staged_parquet, compression="zstd")
            staged_dictionary.write_text(
                dictionary_text.replace(_DICTIONARY_SOURCE, "parquet: bls_index.parquet"),
                encoding="utf-8",
            )
            _run_data_dict_checks(staged_dictionary, root)
            try:
                os.link(staged_parquet, destination)
            except FileExistsError as exc:
                raise CombinedCandidateError(
                    f"candidate output was created concurrently and was not replaced: {destination}"
                ) from exc
    except CombinedCandidateError:
        raise
    except Exception as exc:
        raise CombinedCandidateError(f"cannot stage candidate Parquet: {exc}") from exc
    finally:
        if made_parent:
            try:
                destination.parent.rmdir()
            except OSError:
                pass
    return combined
