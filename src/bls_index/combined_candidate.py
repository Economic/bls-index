"""Combine per-program rows into one catalog candidate and validate it."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import polars as pl

from bls_index.schema import CANONICAL_SCHEMA
from bls_index.scope import INITIAL_PROGRAMS, NATIVE_TITLE_PROGRAMS, SURVEY_ALIASES, SURVEY_NAMES

DICTIONARY = Path(__file__).resolve().parents[2] / "data-dict.yaml"
CATALOG_NAME = "bls_index.parquet"  # the dictionary's relative parquet source


class CombinedCandidateError(ValueError):
    pass


def validate_combined_candidate(
    frames: Mapping[str, pl.DataFrame], requested_programs: Sequence[str]
) -> pl.DataFrame:
    """Check scope, schema, program assignment, and global ID uniqueness; concatenate."""
    programs = tuple(requested_programs)
    if not programs or len(set(programs)) != len(programs):
        raise CombinedCandidateError("requested scope must be nonempty and unique")
    if set(programs) - set(INITIAL_PROGRAMS):
        raise CombinedCandidateError(f"programs outside scope: {sorted(set(programs) - set(INITIAL_PROGRAMS))}")
    if set(frames) != set(programs):
        raise CombinedCandidateError(
            f"frames {sorted(frames)} do not match requested programs {sorted(programs)}"
        )
    for program in programs:
        frame = frames[program]
        if frame.schema != CANONICAL_SCHEMA:
            raise CombinedCandidateError(f"{program}: schema {frame.schema} is not canonical")
        if frame.is_empty():
            raise CombinedCandidateError(f"{program}: no rows")
        source = "native" if program in NATIVE_TITLE_PROGRAMS else "synthesized"
        if not frame.select(
            (pl.col("program") == program).all()
            & (pl.col("survey_name") == SURVEY_NAMES[program]).all()
            & pl.col("survey_aliases").eq_missing(SURVEY_ALIASES.get(program)).all()
            & (pl.col("title_source") == source).all()
        ).item():
            raise CombinedCandidateError(
                f"{program}: wrong program, survey_name, survey_aliases or title_source values"
            )

    combined = pl.concat([frames[program] for program in programs])
    duplicates = combined.filter(pl.col("series_id").is_duplicated())
    if duplicates.height:
        first = duplicates.row(0, named=True)["series_id"]
        owners = sorted(duplicates.filter(pl.col("series_id") == first)["program"].unique())
        raise CombinedCandidateError(f"series_id {first!r} appears in programs {owners}")
    return combined


def write_combined_candidate(
    frames: Mapping[str, pl.DataFrame],
    requested_programs: Sequence[str],
    directory: Path,
) -> pl.DataFrame:
    """Validate, write ``directory/bls_index.parquet``, and run the pinned data-dict checks.

    The dictionary is copied beside the Parquet because ``validate-data`` resolves its
    relative ``parquet:`` source from the dictionary's directory. On any failure the
    Parquet file is removed, so a failed run never leaves a candidate behind.
    """
    combined = validate_combined_candidate(frames, requested_programs)
    directory.mkdir(parents=True, exist_ok=True)
    catalog = directory / CATALOG_NAME
    dictionary = directory / "data-dict.yaml"
    try:
        combined.write_parquet(catalog, compression="zstd", compression_level=19)
        shutil.copyfile(DICTIONARY, dictionary)
        _run_data_dict(dictionary)
    except BaseException:
        catalog.unlink(missing_ok=True)
        raise
    return combined


def _run_data_dict(dictionary: Path) -> None:
    executable = shutil.which("data-dict")
    if executable is None:
        raise CombinedCandidateError("data-dict executable not found on PATH")
    for check in ("validate-spec", "validate-meta", "validate-data"):
        result = subprocess.run(
            [executable, check, str(dictionary), "--json"],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        if result.returncode:
            raise CombinedCandidateError(
                f"data-dict {check} failed (exit {result.returncode}): "
                f"{(result.stdout + result.stderr).strip()}"
            )
