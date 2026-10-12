"""Strict local parsers for the first native-title source adapters.

This module deliberately does not download data, publish files, or infer a program
from an ID. The supported adapters are a bounded first increment of Phase 1.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import polars as pl

SCHEMA_VERSION = 1
SUPPORTED_NATIVE_PROGRAMS = ("ap", "ce", "cu", "ln", "oe")

# Exact source headers observed in docs/evidence/2026-10-07-local-source-probe.json.
SOURCE_HEADERS: dict[str, tuple[str, ...]] = {
    "ap": (
        "series_id", "area_code", "item_code", "series_title", "footnote_codes",
        "begin_year", "begin_period", "end_year", "end_period",
    ),
    "ce": (
        "series_id", "supersector_code", "industry_code", "data_type_code", "seasonal",
        "series_title", "footnote_codes", "begin_year", "begin_period", "end_year",
        "end_period",
    ),
    "cu": (
        "series_id", "area_code", "item_code", "seasonal", "periodicity_code", "base_code",
        "base_period", "series_title", "footnote_codes", "begin_year", "begin_period",
        "end_year", "end_period",
    ),
    "ln": (
        "series_id", "lfst_code", "periodicity_code", "series_title", "absn_code",
        "activity_code", "ages_code", "cert_code", "class_code", "duration_code",
        "education_code", "entr_code", "expr_code", "hheader_code", "hour_code",
        "indy_code", "jdes_code", "look_code", "mari_code", "mjhs_code", "occupation_code",
        "orig_code", "pcts_code", "race_code", "rjnw_code", "rnlf_code", "rwns_code",
        "seek_code", "sexs_code", "tdat_code", "vets_code", "wkst_code", "born_code",
        "chld_code", "disa_code", "seasonal", "tlwk_code", "footnote_codes", "begin_year",
        "begin_period", "end_year", "end_period",
    ),
    "oe": (
        "series_id", "seasonal", "areatype_code", "industry_code", "occupation_code",
        "datatype_code", "state_code", "area_code", "sector_code", "series_title",
        "footnote_codes", "begin_year", "begin_period", "end_year", "end_period",
    ),
}

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

_YEAR_RE = re.compile(r"^[0-9]{4}$")
_SERIES_ID_RE = re.compile(r"^[A-Za-z0-9]+$")
_PERIOD_RE = re.compile(r"^(M|Q|A)([0-9]{2})$")


class NativeSeriesError(ValueError):
    """The source file does not satisfy its observed program contract."""


def _fail(path: Path, message: str, line: int | None = None) -> NativeSeriesError:
    where = f" line {line}" if line is not None else ""
    return NativeSeriesError(f"{path}{where}: {message}")


def _validate_raw_file(path: Path, program: str) -> int:
    """Stream-check UTF-8, controls, exact widths, and nonempty rows before Polars."""
    expected = SOURCE_HEADERS[program]
    row_count = 0
    try:
        stream = path.open("rb")
    except OSError as exc:
        raise _fail(path, f"cannot read source: {exc}") from exc

    with stream:
        header: tuple[str, ...] | None = None
        for line_number, raw_line in enumerate(stream, start=1):
            line = raw_line
            if line.endswith(b"\n"):
                line = line[:-1]
                if line.endswith(b"\r"):
                    line = line[:-1]
            elif b"\r" in line:
                raise _fail(path, "bare carriage return is not a supported line ending", line_number)

            if not line:
                raise _fail(path, "blank lines are not allowed", line_number)
            try:
                decoded_line = line.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise _fail(path, "source is not valid UTF-8", line_number) from exc
            fields = decoded_line.split("\t")
            if any(
                unicodedata.category(char) == "Cc"
                for field in fields
                for char in field
            ):
                raise _fail(path, "control characters are not allowed in source fields", line_number)
            if header is None:
                # BLS headers in the observed files have right-padding before tabs.
                header = tuple(field.strip() for field in fields)
                if header != expected:
                    raise _fail(
                        path,
                        f"unexpected {program!r} header; expected {expected!r}, got {header!r}",
                        line_number,
                    )
                continue

            if len(fields) != len(expected):
                raise _fail(
                    path,
                    f"row has {len(fields)} tab-separated fields; expected {len(expected)}",
                    line_number,
                )
            if not any(field.strip() for field in fields):
                raise _fail(path, "empty data row", line_number)
            row_count += 1

    if header is None:
        raise _fail(path, "source is empty; expected a header")
    if row_count == 0:
        raise _fail(path, "source has a header but no data rows")
    return row_count


def _validate_period(path: Path, values: pl.Series) -> None:
    nonblank = values.filter(values.is_not_null() & (values != ""))
    if nonblank.is_empty():
        return
    families = nonblank.str.extract(_PERIOD_RE.pattern, group_index=1)
    ordinals = nonblank.str.extract(_PERIOD_RE.pattern, group_index=2).cast(pl.Int8, strict=False)
    valid_range = (
        ((families == "M") & ordinals.is_between(1, 13))
        | ((families == "Q") & ordinals.is_between(1, 5))
        | ((families == "A") & (ordinals == 1))
    )
    if (~valid_range.fill_null(False)).any():
        invalid = nonblank.filter(~valid_range.fill_null(False))[0]
        raise _fail(path, f"invalid period code {invalid!r}; expected a supported BLS period code")


def parse_native_series(path: str | Path, program: str) -> pl.DataFrame:
    """Parse one local native-title ``.series`` file to canonical schema v1.

    ``path`` and ``program`` are both explicit. The returned Polars frame preserves source
    row order and native title content; only the padded ID and metadata fields are trimmed.
    """
    path = Path(path)
    if program not in SUPPORTED_NATIVE_PROGRAMS:
        raise NativeSeriesError(
            f"unsupported native program {program!r}; supported: {SUPPORTED_NATIVE_PROGRAMS!r}"
        )

    source_rows = _validate_raw_file(path, program)
    source_header = SOURCE_HEADERS[program]
    try:
        source = pl.read_csv(
            path,
            separator="\t",
            has_header=False,
            skip_rows=1,
            new_columns=list(source_header),
            schema_overrides={name: pl.String for name in source_header},
            infer_schema=False,
            quote_char=None,
            encoding="utf8",
            low_memory=True,
            raise_if_empty=True,
        )
    except Exception as exc:
        raise _fail(path, f"Polars could not parse the validated tabular source: {exc}") from exc

    if source.height != source_rows or source.width != len(source_header):
        raise _fail(
            path,
            f"parsed shape {source.shape} does not match validated source rows/columns "
            f"({source_rows}, {len(source_header)})",
        )

    normalized = source.with_columns(
        pl.col("series_id").str.strip_chars().alias("series_id"),
        *[
            pl.col(name).str.strip_chars().alias(name)
            for name in ("begin_year", "begin_period", "end_year", "end_period", "seasonal")
            if name in source.columns
        ],
    )

    bad_id = normalized.filter(
        pl.col("series_id").is_null()
        | (pl.col("series_id") == "")
        | ~pl.col("series_id").str.contains(_SERIES_ID_RE.pattern)
    )
    if bad_id.height:
        raise _fail(path, f"invalid series_id at data row {bad_id.row(0, named=True)}")
    if normalized.get_column("series_id").is_duplicated().any():
        duplicate_id = (
            normalized.filter(pl.col("series_id").is_duplicated())
            .get_column("series_id")[0]
        )
        raise _fail(path, f"duplicate series_id {duplicate_id!r} within program {program!r}")

    bad_title = normalized.filter(
        pl.col("series_title").is_null() | (pl.col("series_title").str.strip_chars() == "")
    )
    if bad_title.height:
        raise _fail(path, "missing or whitespace-only series_title")

    if "seasonal" in normalized.columns:
        seasonal_codes = normalized.get_column("seasonal").unique().to_list()
        invalid_seasonal = sorted(code for code in seasonal_codes if code not in {"S", "U"})
        if invalid_seasonal:
            raise _fail(path, f"invalid or missing seasonal source code(s): {invalid_seasonal!r}")
        seasonal_expr = (
            pl.when(pl.col("seasonal") == "S").then(pl.lit("SA"))
            .when(pl.col("seasonal") == "U").then(pl.lit("NSA"))
            .otherwise(pl.lit("unknown"))
            .alias("seasonal")
        )
    else:
        seasonal_expr = pl.lit("unknown", dtype=pl.String).alias("seasonal")

    for name in ("begin_year", "end_year"):
        values = normalized.get_column(name)
        invalid = values.filter(
            (values != "") & ~values.str.contains(_YEAR_RE.pattern)
        )
        if len(invalid):
            raise _fail(path, f"invalid {name} value {invalid[0]!r}; expected a four-digit year")
        invalid_zero = values.filter(values == "0000")
        if len(invalid_zero):
            raise _fail(path, f"invalid {name} value '0000'; year must be positive")

    # Convert blank optional metadata to null. The source's begin_period is deliberately
    # not included in schema v1; only end_period is retained.
    years = [
        pl.when(pl.col(name) == "").then(None).otherwise(pl.col(name)).cast(pl.Int32).alias(name)
        for name in ("begin_year", "end_year")
    ]
    normalized = normalized.with_columns(*years)
    begin_year = pl.col("begin_year")
    end_year = pl.col("end_year")
    inverted = normalized.filter(
        begin_year.is_not_null() & end_year.is_not_null() & (begin_year > end_year)
    )
    if inverted.height:
        row = inverted.row(0, named=True)
        raise _fail(path, f"begin_year exceeds end_year for series_id {row['series_id']!r}")

    _validate_period(path, normalized.get_column("begin_period"))
    _validate_period(path, normalized.get_column("end_period"))
    has_begin_period_without_year = normalized.filter(
        pl.col("begin_period").is_not_null()
        & (pl.col("begin_period") != "")
        & pl.col("begin_year").is_null()
    )
    if has_begin_period_without_year.height:
        raise _fail(path, "begin_period is present while begin_year is missing")
    has_period_without_year = normalized.filter(
        pl.col("end_period").is_not_null()
        & (pl.col("end_period") != "")
        & pl.col("end_year").is_null()
    )
    if has_period_without_year.height:
        raise _fail(path, "end_period is present while end_year is missing")

    # Native title values are neither stripped nor reconstructed.
    result = normalized.select(
        pl.lit(program, dtype=pl.String).alias("program"),
        pl.col("series_id"),
        pl.col("series_title"),
        pl.lit("native", dtype=pl.String).alias("title_source"),
        seasonal_expr,
        pl.col("begin_year"),
        pl.col("end_year"),
        pl.when(pl.col("end_period") == "").then(None).otherwise(pl.col("end_period"))
        .cast(pl.String).alias("end_period"),
    )
    return result.cast(CANONICAL_SCHEMA)
