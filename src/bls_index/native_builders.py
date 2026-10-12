"""Strict local parsers for the first native-title source adapters.

This module deliberately does not download data, publish files, or infer a program
from an ID. The supported adapters are a bounded first increment of Phase 1.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
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
_COPY_CHUNK_SIZE = 1024 * 1024


class NativeSeriesError(ValueError):
    """The source file does not satisfy its observed program contract."""


def _fail(path: Path, message: str, line: int | None = None) -> NativeSeriesError:
    where = f" line {line}" if line is not None else ""
    return NativeSeriesError(f"{path}{where}: {message}")


def _copy_to_snapshot(source: Path, snapshot: Path) -> str:
    """Copy the input once into private staging while hashing exactly the copied bytes."""
    digest = hashlib.sha256()
    try:
        with source.open("rb") as source_stream, snapshot.open("xb") as target_stream:
            while chunk := source_stream.read(_COPY_CHUNK_SIZE):
                target_stream.write(chunk)
                digest.update(chunk)
            target_stream.flush()
    except OSError as exc:
        raise _fail(source, f"cannot stage source snapshot: {exc}") from exc
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(_COPY_CHUNK_SIZE):
                digest.update(chunk)
    except OSError as exc:
        raise _fail(path, f"cannot verify source after parsing: {exc}") from exc
    return digest.hexdigest()


def _validate_raw_file(path: Path, program: str, diagnostic_path: Path | None = None) -> int:
    """Stream-check UTF-8, controls, exact widths, and nonempty rows before Polars."""
    report_path = diagnostic_path or path
    expected = SOURCE_HEADERS[program]
    row_count = 0
    try:
        stream = path.open("rb")
    except OSError as exc:
        raise _fail(report_path, f"cannot read staged source: {exc}") from exc

    with stream:
        header: tuple[str, ...] | None = None
        for line_number, raw_line in enumerate(stream, start=1):
            line = raw_line
            if line.endswith(b"\n"):
                line = line[:-1]
                if line.endswith(b"\r"):
                    line = line[:-1]
            elif b"\r" in line:
                raise _fail(report_path, "bare carriage return is not a supported line ending", line_number)

            if not line:
                raise _fail(report_path, "blank lines are not allowed", line_number)
            try:
                decoded_line = line.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise _fail(report_path, "source is not valid UTF-8", line_number) from exc
            fields = decoded_line.split("\t")
            if any(
                unicodedata.category(char) == "Cc"
                for field in fields
                for char in field
            ):
                raise _fail(report_path, "control characters are not allowed in source fields", line_number)
            if header is None:
                # BLS headers in the observed files have right-padding before tabs.
                header = tuple(field.strip() for field in fields)
                if header != expected:
                    raise _fail(
                        report_path,
                        f"unexpected {program!r} header; expected {expected!r}, got {header!r}",
                        line_number,
                    )
                continue

            if len(fields) != len(expected):
                raise _fail(
                    report_path,
                    f"row has {len(fields)} tab-separated fields; expected {len(expected)}",
                    line_number,
                )
            if not any(field.strip() for field in fields):
                raise _fail(report_path, "empty data row", line_number)
            row_count += 1

    if header is None:
        raise _fail(report_path, "source is empty; expected a header")
    if row_count == 0:
        raise _fail(report_path, "source has a header but no data rows")
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


def _parse_snapshot(snapshot: Path, source_path: Path, program: str) -> pl.DataFrame:
    source_rows = _validate_raw_file(snapshot, program, diagnostic_path=source_path)
    source_header = SOURCE_HEADERS[program]
    try:
        source = pl.read_csv(
            snapshot,
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
        raise _fail(source_path, f"Polars could not parse the validated staged source: {exc}") from exc

    if source.height != source_rows or source.width != len(source_header):
        raise _fail(
            source_path,
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
        raise _fail(source_path, f"invalid series_id at data row {bad_id.row(0, named=True)}")
    if normalized.get_column("series_id").is_duplicated().any():
        duplicate_id = (
            normalized.filter(pl.col("series_id").is_duplicated())
            .get_column("series_id")[0]
        )
        raise _fail(source_path, f"duplicate series_id {duplicate_id!r} within program {program!r}")

    bad_title = normalized.filter(
        pl.col("series_title").is_null() | (pl.col("series_title").str.strip_chars() == "")
    )
    if bad_title.height:
        raise _fail(source_path, "missing or whitespace-only series_title")

    if "seasonal" in normalized.columns:
        seasonal_codes = normalized.get_column("seasonal").unique().to_list()
        invalid_seasonal = [code for code in seasonal_codes if code not in {"S", "U"}]
        if invalid_seasonal:
            invalid_seasonal.sort(key=lambda code: (code is not None, str(code)))
            raise _fail(source_path, f"invalid or missing seasonal source code(s): {invalid_seasonal!r}")
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
            raise _fail(source_path, f"invalid {name} value {invalid[0]!r}; expected a four-digit year")
        invalid_zero = values.filter(values == "0000")
        if len(invalid_zero):
            raise _fail(source_path, f"invalid {name} value '0000'; year must be positive")

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
        raise _fail(source_path, f"begin_year exceeds end_year for series_id {row['series_id']!r}")

    _validate_period(source_path, normalized.get_column("begin_period"))
    _validate_period(source_path, normalized.get_column("end_period"))
    has_begin_period_without_year = normalized.filter(
        pl.col("begin_period").is_not_null()
        & (pl.col("begin_period") != "")
        & pl.col("begin_year").is_null()
    )
    if has_begin_period_without_year.height:
        raise _fail(source_path, "begin_period is present while begin_year is missing")
    has_period_without_year = normalized.filter(
        pl.col("end_period").is_not_null()
        & (pl.col("end_period") != "")
        & pl.col("end_year").is_null()
    )
    if has_period_without_year.height:
        raise _fail(source_path, "end_period is present while end_year is missing")

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


def parse_native_series(path: str | Path, program: str) -> pl.DataFrame:
    """Parse one local native-title ``.series`` file to canonical schema v1.

    ``path`` and ``program`` are both explicit. Input is privately staged once, then the
    same snapshot is validated and parsed. The original path is rehashed after parsing so
    a source change during the operation fails with ``NativeSeriesError``. The returned
    Polars frame preserves source row order and native title content; only the padded ID
    and metadata fields are trimmed.
    """
    path = Path(path)
    if program not in SUPPORTED_NATIVE_PROGRAMS:
        raise NativeSeriesError(
            f"unsupported native program {program!r}; supported: {SUPPORTED_NATIVE_PROGRAMS!r}"
        )

    try:
        with tempfile.TemporaryDirectory(prefix="bls-index-native-") as staging_dir:
            snapshot = Path(staging_dir) / "source.series"
            snapshot_sha256 = _copy_to_snapshot(path, snapshot)
            before_validation_sha256 = _sha256_file(path)
            if before_validation_sha256 != snapshot_sha256:
                raise _fail(
                    path,
                    "source changed while staging; the staged snapshot and source "
                    f"checksums differ ({snapshot_sha256} != {before_validation_sha256})",
                )

            result = _parse_snapshot(snapshot, path, program)
            after_parse_sha256 = _sha256_file(path)
            if after_parse_sha256 != snapshot_sha256:
                raise _fail(
                    path,
                    "source changed while parsing; the staged snapshot and source "
                    f"checksums differ ({snapshot_sha256} != {after_parse_sha256})",
                )
            return result
    except NativeSeriesError:
        raise
    except OSError as exc:
        raise _fail(path, f"cannot stage or clean up source snapshot: {exc}") from exc
