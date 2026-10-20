"""Catalog schema v1 and the shared rules for reading BLS tab-separated files."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import polars as pl

SCHEMA_VERSION = 1

CANONICAL_SCHEMA: dict[str, pl.DataType] = {
    "program": pl.String,
    "series_id": pl.String,
    "series_title": pl.String,
    "title_source": pl.String,
    "seasonal": pl.String,
    "begin_year": pl.Int32,
    "end_year": pl.Int32,
    "end_period": pl.String,
}

log = logging.getLogger(__name__)


class BuildError(ValueError):
    """A source file cannot be turned into catalog rows."""


def read_tsv(path: Path, needed: Sequence[str], optional: Sequence[str] = ()) -> pl.DataFrame:
    """Read a BLS tab-separated file as strings, keeping ``needed`` and any ``optional`` columns.

    Columns are found by name in the trimmed header, so added or reordered columns are
    accepted. Every data row must have exactly the header's field count: a missing or
    extra tab would otherwise shift values into the wrong columns.
    """
    try:
        with path.open("rb") as stream:
            first = stream.readline()
            width = first.count(b"\t")
            rows = 0
            for line_number, line in enumerate(stream, start=2):
                if line.count(b"\t") != width:
                    raise BuildError(
                        f"{path} line {line_number}: expected {width + 1} tab-separated fields"
                    )
                rows += 1
        header = [name.strip() for name in first.rstrip(b"\r\n").decode("utf-8").split("\t")]
    except OSError as exc:
        raise BuildError(f"{path}: cannot read: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise BuildError(f"{path}: header is not valid UTF-8") from exc
    if not first:
        raise BuildError(f"{path}: file is empty")
    if rows == 0:
        raise BuildError(f"{path}: no data rows")
    if len(set(header)) != len(header):
        raise BuildError(f"{path}: duplicate column names in header {header!r}")
    missing = [name for name in needed if name not in header]
    if missing:
        raise BuildError(f"{path}: missing column(s) {missing!r}")
    keep = [*needed, *(name for name in optional if name in header)]
    try:
        frame = pl.scan_csv(
            path, separator="\t", has_header=False, skip_rows=1, new_columns=header,
            infer_schema=False, quote_char=None, encoding="utf8",
        ).select(keep).collect()  # fmt: skip
    except Exception as exc:  # polars raises several types for malformed input
        raise BuildError(f"{path}: cannot parse: {exc}") from exc
    if frame.height != rows:
        raise BuildError(f"{path}: parsed {frame.height} rows, expected {rows}")
    return frame


def _blank(column: str) -> pl.Expr:
    return pl.col(column).is_null() | (pl.col(column).str.strip_chars() == "")


def _first(frame: pl.DataFrame, condition: pl.Expr, column: str) -> object | None:
    found = frame.filter(condition)
    return found.get_column(column)[0] if found.height else None


def canonical_rows(frame: pl.DataFrame, program: str, title_source: str, where: str) -> pl.DataFrame:
    """Check and normalize parsed source rows into the canonical schema.

    ``frame`` has string columns ``series_id``, ``series_title``, ``begin_year``,
    ``end_year``, ``end_period`` and optionally ``seasonal``. Titles are kept exactly
    as given; every other field is trimmed, and blanks become null.
    """
    trimmed = ["series_id", "begin_year", "end_year", "end_period"]
    if "seasonal" in frame.columns:
        trimmed.append("seasonal")
    frame = frame.with_columns(
        pl.col(name).str.strip_chars().replace("", None) for name in trimmed
    )

    if frame.get_column("series_id").null_count():
        raise BuildError(f"{where}: blank series_id")
    prefix = program.upper()
    bad = _first(frame, ~pl.col("series_id").str.to_uppercase().str.starts_with(prefix), "series_id")
    if bad is not None:
        raise BuildError(f"{where}: series_id {bad!r} does not start with {prefix!r}")
    dup = _first(frame, pl.col("series_id").is_duplicated(), "series_id")
    if dup is not None:
        raise BuildError(f"{where}: duplicate series_id {dup!r}")
    if frame.select(_blank("series_title").any()).item():
        raise BuildError(f"{where}: blank series_title")
    for name in ("begin_year", "end_year"):
        bad = _first(frame, pl.col(name).is_not_null() & ~pl.col(name).str.contains(r"^[0-9]{4}$"), name)
        if bad is not None:
            raise BuildError(f"{where}: {name} {bad!r} is not a four-digit year")

    if "seasonal" in frame.columns:
        code = pl.col("seasonal")
        unexpected = frame.filter(code.is_null() | ~code.is_in(["S", "U"])).height
        if unexpected:
            log.warning("%s: %d rows with a seasonal code other than S or U", where, unexpected)
        seasonal = pl.when(code == "S").then(pl.lit("SA")).when(code == "U").then(pl.lit("NSA"))
        seasonal = seasonal.otherwise(pl.lit("unknown"))
    else:
        seasonal = pl.lit("unknown")

    return frame.select(
        pl.lit(program).alias("program"),
        "series_id",
        "series_title",
        pl.lit(title_source).alias("title_source"),
        seasonal.alias("seasonal"),
        "begin_year",
        "end_year",
        "end_period",
    ).cast(CANONICAL_SCHEMA)
