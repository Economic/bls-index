"""Strict local parsers for all 30 fixed native-title source adapters.

This module deliberately does not download data, publish files, or infer a program
from an ID. Source contracts are explicit and versioned in code; probe reports are
evidence for tests and documentation, never runtime configuration.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
import unicodedata
from pathlib import Path

import polars as pl

SCHEMA_VERSION = 1
SUPPORTED_NATIVE_PROGRAMS = (
    "oe", "is", "wm", "cx", "ep", "nb", "tu", "or", "ln", "bd",
    "la", "ce", "ip", "le", "wd", "cu", "cm", "cw", "nd", "wp",
    "mp", "pc", "fm", "ci", "ei", "ap", "kv", "lu", "su", "ws",
)

# Exact current .series header tuples observed in the local 2026-10-07 probe.
# Do not replace these with a header-driven or report-loaded production contract.
SOURCE_HEADERS: dict[str, tuple[str, ...]] = {
    "oe": (
        "series_id", "seasonal", "areatype_code", "industry_code", "occupation_code",
        "datatype_code", "state_code", "area_code", "sector_code", "series_title",
        "footnote_codes", "begin_year", "begin_period", "end_year", "end_period",
    ),
    "is": (
        "series_id", "seasonal", "supersector_code", "industry_code", "data_type_code",
        "case_type_code", "area_code", "series_title", "footnote_codes", "begin_year",
        "begin_period", "end_year", "end_period",
    ),
    "wm": (
        "series_id", "seasonal", "area_code", "ownership_code", "estimate_code",
        "industry_code", "occupation_code", "subcell_code", "datatype_code", "level_code",
        "series_title", "footnote_codes", "begin_year", "begin_period", "end_year",
        "end_period",
    ),
    "cx": (
        "series_id", "seasonal", "category_code", "subcategory_code", "item_code",
        "demographics_code", "characteristics_code", "process_code", "series_title",
        "footnote_codes", "begin_year", "begin_period", "end_year", "end_period",
    ),
    "ep": (
        "series_id", "seasonal", "occ_type", "ind_type", "occ_code", "ind_code",
        "wkex_code", "rank_code", "otjt_code", "eductrn_code", "disp_code",
        "series_title", "footnote_codes", "begin_year", "begin_period", "end_year",
        "end_period",
    ),
    "nb": (
        "series_id", "seasonal", "ownership_code", "estimate_code", "industry_code",
        "occupation_code", "subcell_code", "datatype_code", "provision_code", "survey_code",
        "series_title", "footnote_codes", "begin_year", "begin_period", "end_year",
        "end_period",
    ),
    "tu": (
        "series_id", "seasonal", "stattype_code", "datays_code", "sex_code", "region_code",
        "lfstat_code", "educ_code", "maritlstat_code", "age_code", "orig_code", "race_code",
        "mjcow_code", "nmet_code", "where_code", "sjmj_code", "timeday_code", "actcode_code",
        "industry_code", "occ_code", "prhhchild_code", "earn_code", "disability_code",
        "who_code", "hhnscc03_code", "schenr_code", "prownhhchild_code", "work_code",
        "elnum_code", "ecage_code", "elfreq_code", "eldur_code", "elwho_code", "ecytd_code",
        "elder_code", "lfstatw_code", "pertype_code", "series_title", "footnote_codes",
        "begin_year", "begin_period", "end_year", "end_period",
    ),
    "or": (
        "series_id", "seasonal", "ownership_code", "industry_code", "occupation_code",
        "soc_code", "job_characteristic_code", "estimate_code", "datatype_code",
        "category_code", "additive_code", "requirement_code", "series_title", "footnote_codes",
        "begin_year", "begin_period", "end_year", "end_period",
    ),
    "ln": (
        "series_id", "lfst_code", "periodicity_code", "series_title", "absn_code",
        "activity_code", "ages_code", "cert_code", "class_code", "duration_code",
        "education_code", "entr_code", "expr_code", "hheader_code", "hour_code", "indy_code",
        "jdes_code", "look_code", "mari_code", "mjhs_code", "occupation_code", "orig_code",
        "pcts_code", "race_code", "rjnw_code", "rnlf_code", "rwns_code", "seek_code",
        "sexs_code", "tdat_code", "vets_code", "wkst_code", "born_code", "chld_code",
        "disa_code", "seasonal", "tlwk_code", "footnote_codes", "begin_year", "begin_period",
        "end_year", "end_period",
    ),
    "bd": (
        "series_id", "seasonal", "msa_code", "state_code", "county_code", "industry_code",
        "unitanalysis_code", "dataelement_code", "sizeclass_code", "dataclass_code",
        "ratelevel_code", "periodicity_code", "ownership_code", "series_title", "footnote_codes",
        "begin_year", "begin_period", "end_year", "end_period",
    ),
    "la": (
        "series_id", "area_type_code", "area_code", "measure_code", "seasonal", "srd_code",
        "series_title", "footnote_codes", "begin_year", "begin_period", "end_year", "end_period",
    ),
    "ce": (
        "series_id", "supersector_code", "industry_code", "data_type_code", "seasonal",
        "series_title", "footnote_codes", "begin_year", "begin_period", "end_year", "end_period",
    ),
    "ip": (
        "series_id", "seasonal", "sector_code", "industry_code", "measure_code", "duration_code",
        "base_year", "type_code", "area_code", "series_title", "footnote_codes", "begin_year",
        "begin_period", "end_year", "end_period",
    ),
    "le": (
        "series_id", "lfst_code", "fips_code", "series_title", "tdata_code", "pcts_code",
        "earn_code", "cert_code", "class_code", "unin_code", "indy_code", "occupation_code",
        "education_code", "ages_code", "race_code", "orig_code", "sexs_code", "born_code",
        "seasonal", "footnote_codes", "begin_year", "begin_period", "end_year", "end_period",
    ),
    "wd": (
        "series_id", "group_code", "item_code", "seasonal", "base_date", "series_title",
        "footnote_codes", "begin_year", "begin_period", "end_year", "end_period",
    ),
    "cu": (
        "series_id", "area_code", "item_code", "seasonal", "periodicity_code", "base_code",
        "base_period", "series_title", "footnote_codes", "begin_year", "begin_period", "end_year",
        "end_period",
    ),
    "cm": (
        "series_id", "seasonal", "owner_code", "industry_code", "occupation_code", "subcell_code",
        "area_code", "datatype_code", "estimate_code", "series_title", "footnote_codes",
        "begin_year", "begin_period", "end_year", "end_period",
    ),
    "cw": (
        "series_id", "area_code", "item_code", "seasonal", "periodicity_code", "base_code",
        "base_period", "series_title", "footnote_codes", "begin_year", "begin_period", "end_year",
        "end_period",
    ),
    "nd": (
        "series_id", "industry_code", "product_code", "seasonal", "base_date", "series_title",
        "footnote_codes", "begin_year", "begin_period", "end_year", "end_period",
    ),
    "wp": (
        "series_id", "group_code", "item_code", "seasonal", "base_date", "series_title",
        "footnote_codes", "begin_year", "begin_period", "end_year", "end_period",
    ),
    "mp": (
        "series_id", "sector_code", "measure_code", "duration_code", "base_year", "series_title",
        "footnote_codes", "begin_year", "begin_period", "end_year", "end_period",
    ),
    "pc": (
        "series_id", "industry_code", "product_code", "seasonal", "base_date", "series_title",
        "footnote_codes", "begin_year", "begin_period", "end_year", "end_period",
    ),
    "fm": (
        "series_id", "seasonal", "series_title", "fchld_code", "fdat_code", "fhlf_code",
        "fnmatwk_code", "fnme_code", "fnmlf_code", "fnmu_code", "fnmws_code", "forig_code",
        "frace_code", "ftpt_code", "ftyp_code", "hhlf_code", "misclf_code", "mwlf_code",
        "prlf_code", "chld_code", "lfst_code", "mari_code", "orig_code", "race_code",
        "sexs_code", "tdat_code", "wkst_code", "footnote_codes", "begin_year", "begin_period",
        "end_year", "end_period",
    ),
    "ci": (
        "series_id", "seasonal", "owner_code", "industry_code", "occupation_code", "subcell_code",
        "area_code", "periodicity_code", "estimate_code", "series_title", "footnote_codes",
        "begin_year", "begin_period", "end_year", "end_period",
    ),
    "ei": (
        "series_id", "seasonal", "index_code", "series_name", "base_period", "series_title",
        "footnote_codes", "begin_year", "begin_period", "end_year", "end_period",
    ),
    "ap": (
        "series_id", "area_code", "item_code", "series_title", "footnote_codes", "begin_year",
        "begin_period", "end_year", "end_period",
    ),
    "kv": (
        "series_id", "seasonal", "footnote_codes", "lfst_code", "series_title", "ages_code",
        "clas_code", "indy_code", "pcts_code", "rsng_code", "scdr_code", "sexs_code",
        "tdat_code", "vets_code", "begin_year", "begin_period", "end_year", "end_period",
    ),
    "lu": (
        "series_id", "lfst_code", "fips_code", "series_title", "tdata_code", "pcts_code",
        "earn_code", "class_code", "unin_code", "indy_code", "occupation_code", "education_code",
        "ages_code", "race_code", "orig_code", "sexs_code", "seasonal", "footnote_codes",
        "begin_year", "begin_period", "end_year", "end_period",
    ),
    "su": (
        "series_id", "area_code", "item_code", "seasonal", "periodicity_code", "base_code",
        "base_period", "series_title", "footnote_codes", "begin_year", "begin_period", "end_year",
        "end_period",
    ),
    "ws": (
        "series_id", "measure_code", "seasonal", "series_title", "footnote_codes", "begin_year",
        "begin_period", "end_year", "end_period",
    ),
}

# Per-program meanings are grounded in the official sources listed in
# docs/native-source-contracts.md. Known seasonal fields reject blank and unsupported codes.
SEASONAL_SOURCE_CODES: dict[str, frozenset[str] | None] = {
    "oe": frozenset({"S", "U"}),
    "is": frozenset({"S", "U"}),
    "wm": frozenset({"S", "U"}),
    "cx": frozenset({"U"}),
    "ep": frozenset({"S", "U"}),
    "nb": frozenset({"S", "U"}),
    "tu": frozenset({"S", "U"}),
    "or": frozenset({"S", "U"}),
    "ln": frozenset({"S", "U"}),
    "bd": frozenset({"S", "U"}),
    "la": frozenset({"S", "U"}),
    "ce": frozenset({"S", "U"}),
    "ip": frozenset({"S", "U"}),
    "le": frozenset({"S", "U"}),
    "wd": frozenset({"S", "U"}),
    "cu": frozenset({"S", "U"}),
    "cm": frozenset({"S", "U"}),
    "cw": frozenset({"S", "U"}),
    "nd": frozenset({"S", "U"}),
    "wp": frozenset({"S", "U"}),
    "mp": None,
    "pc": frozenset({"S", "U"}),
    "fm": frozenset({"S", "U"}),
    "ci": frozenset({"S", "U"}),
    "ei": frozenset({"S", "U"}),
    "ap": None,
    "kv": frozenset({"U"}),
    "lu": frozenset({"S", "U"}),
    "su": frozenset({"S", "U"}),
    "ws": frozenset({"S", "U"}),
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
_PERIOD_RE = re.compile(r"^(M|Q|A|S)([0-9]{2})$")

# The program ID examples in each official .txt identify the owning survey with
# these leading codes (CX is confirmed from its .series file because cx.txt is 404).
# Native IDs are checked against their own documented/exampled shape; a shared prefix
# and a permissive punctuation set are not sufficient assignment validation.
SERIES_ID_PREFIXES: dict[str, str] = {
    "oe": "OE", "is": "IS", "wm": "WM", "cx": "CX",
    "ep": "EP", "nb": "NB", "tu": "TU", "or": "OR",
    "ln": "LN", "bd": "BD", "la": "LA", "ce": "CE",
    "ip": "IP", "le": "LE", "wd": "WD", "cu": "CU",
    "cm": "CM", "cw": "CW", "nd": "ND", "wp": "WP",
    "mp": "MP", "pc": "PC", "fm": "FM", "ci": "CI",
    "ei": "EI", "ap": "AP", "kv": "KV", "lu": "LU",
    "su": "SU", "ws": "WS", "sm": "SM", "jt": "JT", "pr": "PR",
}

# Inclusive lengths after trimming right-padding. Ranges include the valid variants
# recorded in the checked-in native samples and saved full-file revalidation output.
SERIES_ID_LENGTHS: dict[str, tuple[int, int]] = {
    "ap": (12, 13), "bd": (28, 30), "ce": (13, 13), "ci": (17, 17),
    "cm": (17, 17), "cu": (11, 16), "cw": (11, 16), "cx": (16, 17),
    "ei": (10, 14), "ep": (14, 15), "fm": (7, 11), "ip": (21, 21),
    "is": (17, 17), "kv": (19, 19), "la": (20, 20), "le": (13, 13),
    "ln": (11, 12), "lu": (13, 13), "mp": (9, 10), "nb": (14, 23),
    "nd": (15, 24), "oe": (25, 25), "or": (20, 20), "pc": (15, 22),
    "su": (11, 14), "tu": (18, 18), "wd": (6, 11), "wm": (29, 29),
    "wp": (5, 11), "ws": (6, 6),
}

# Separators accepted in the observed ID families. Component checks constrain
# their placement for programs with a verified source-column layout.
SERIES_ID_SEPARATORS: dict[str, str] = {"ip": "_", "nd": "-", "oe": "-", "pc": "-"}
SERIES_ID_SEASON_CODES: dict[str, str] = {p: "SU" for p in SUPPORTED_NATIVE_PROGRAMS}
SERIES_ID_SEASON_CODES.update({"ap": "U", "cx": "U", "kv": "U", "mp": "U"})

# ID component layouts are compared only where their order and source-column mapping
# are supported by official examples, checked-in native samples, or saved parsed-row
# evidence. Literal components are used for AP (no seasonal column) and the CPI programs
# whose IDs encode dimensions in a different order from their .series headers.
SERIES_ID_COMPONENTS: dict[str, tuple[str, ...]] = {
    "ap": ("U", "area_code", "item_code"),
    "cx": ("seasonal", "item_code", "demographics_code", "characteristics_code", "process_code"),
    "oe": ("seasonal", "areatype_code", "area_code", "industry_code", "occupation_code", "datatype_code"),
    "bd": ("seasonal", "msa_code", "state_code", "county_code", "industry_code",
           "unitanalysis_code", "dataelement_code", "sizeclass_code", "dataclass_code",
           "ratelevel_code", "periodicity_code", "ownership_code"),
    "ce": ("seasonal", "supersector_code", "industry_code", "data_type_code"),
    "cu": ("seasonal", "periodicity_code", "area_code", "item_code"),
    "cw": ("seasonal", "periodicity_code", "area_code", "item_code"),
    "ip": ("seasonal", "sector_code", "industry_code", "measure_code", "duration_code", "area_code"),
    "nd": ("seasonal", "industry_code", "product_code"),
    "pc": ("seasonal", "industry_code", "product_code"),
    "su": ("seasonal", "periodicity_code", "area_code", "item_code"),
    "wd": ("seasonal", "group_code", "item_code"),
    "wp": ("seasonal", "group_code", "item_code"),
}


def series_id_pattern(program: str) -> str:
    """Regex for the documented ID shape of an explicitly selected program."""
    if program not in SUPPORTED_NATIVE_PROGRAMS:
        raise KeyError(program)
    minimum, maximum = SERIES_ID_LENGTHS[program]
    separator = re.escape(SERIES_ID_SEPARATORS.get(program, ""))
    rest_chars = f"A-Z0-9{separator}"
    minimum_rest, maximum_rest = minimum - 3, maximum - 3
    return (
        rf"^{SERIES_ID_PREFIXES[program]}[{SERIES_ID_SEASON_CODES[program]}]"
        rf"[{rest_chars}]{{{minimum_rest},{maximum_rest}}}$"
    )


SERIES_ID_PATTERNS: dict[str, str] = {
    program: series_id_pattern(program) for program in SUPPORTED_NATIVE_PROGRAMS
}


def valid_series_id(series_id: str, program: str) -> bool:
    """Return whether an ID matches the explicit native program's documented shape."""
    if program in SERIES_ID_PATTERNS:
        return re.fullmatch(SERIES_ID_PATTERNS[program], series_id.upper()) is not None
    # Synthesized-title programs are not covered by native-title ID shapes. Keep their
    # check to the observed ownership code and ASCII ID alphabet until documented lengths
    # and dimensions are available.
    return (
        program in {"sm", "jt", "pr"}
        and bool(re.fullmatch(r"[A-Za-z0-9_-]+", series_id))
        and series_id.upper().startswith(SERIES_ID_PREFIXES[program])
    )


def _series_id_components_expr(program: str) -> pl.Expr:
    parts = []
    for part in SERIES_ID_COMPONENTS[program]:
        if part not in SOURCE_HEADERS[program]:
            parts.append(pl.lit(part))
        elif program == "ce" and part == "industry_code":
            # CES IDs use the six-digit industry suffix; the source column also
            # contains its two-digit supersector prefix.
            parts.append(pl.col(part).str.strip_chars().str.slice(-6))
        elif program == "wp" and part == "item_code":
            # In this commodity series, a dash in the source is a no-item
            # sentinel and is not included in the series ID.
            parts.append(
                pl.when(pl.col(part).str.strip_chars() == "-")
                .then(pl.lit("")).otherwise(pl.col(part).str.strip_chars())
            )
        else:
            parts.append(pl.col(part).str.strip_chars())
    return pl.concat_str([pl.lit(SERIES_ID_PREFIXES[program]), *parts])
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
            if any(unicodedata.category(char) == "Cc" for field in fields for char in field):
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


def _validate_period(path: Path, values: pl.Series, program: str) -> None:
    nonblank = values.filter(values.is_not_null() & (values != ""))
    if nonblank.is_empty():
        return
    families = nonblank.str.extract(_PERIOD_RE.pattern, group_index=1)
    ordinals = nonblank.str.extract(_PERIOD_RE.pattern, group_index=2).cast(pl.Int8, strict=False)
    monthly = (families == "M") & ordinals.is_between(1, 13)
    if program in {"cu", "cw"}:
        valid_range = monthly | ((families == "S") & ordinals.is_between(1, 3))
    else:
        valid_range = (
            monthly
            | ((families == "Q") & ordinals.is_between(1, 5))
            | ((families == "A") & (ordinals == 1))
        )
    if (~valid_range.fill_null(False)).any():
        invalid = nonblank.filter(~valid_range.fill_null(False))[0]
        raise _fail(path, f"invalid period code {invalid!r}; expected a supported BLS period code")


def _seasonal_expression(path: Path, program: str, source: pl.DataFrame) -> pl.Expr:
    if "seasonal" not in source.columns:
        return pl.lit("unknown", dtype=pl.String).alias("seasonal")

    values = source.get_column("seasonal").str.strip_chars()
    nonblank = values.filter(values.is_not_null() & (values != ""))
    allowed = SEASONAL_SOURCE_CODES[program]
    if allowed is None:
        if nonblank.len():
            codes = sorted(nonblank.unique().to_list())
            raise _fail(
                path,
                f"seasonal source mapping is not verified for program {program!r}; "
                f"observed nonblank code(s): {codes!r}",
            )
        return pl.lit("unknown", dtype=pl.String).alias("seasonal")

    invalid = sorted(
        set(values.unique().to_list()) - allowed,
        key=lambda value: (value is not None, value or ""),
    )
    if invalid:
        raise _fail(
            path,
            f"invalid, blank, or missing seasonal source code(s) for {program!r}: {invalid!r}; "
            f"allowed: {sorted(allowed)!r}",
        )
    return (
        pl.when(values == "S").then(pl.lit("SA"))
        .when(values == "U").then(pl.lit("NSA"))
        .otherwise(pl.lit("unknown"))
        .alias("seasonal")
    )


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

    seasonal_expr = _seasonal_expression(source_path, program, normalized)

    expected_id = (
        _series_id_components_expr(program)
        if program in SERIES_ID_COMPONENTS
        else None
    )
    bad_id = normalized.filter(
        pl.col("series_id").is_null()
        | ~pl.col("series_id").str.to_uppercase().str.contains(SERIES_ID_PATTERNS[program])
        | (pl.col("series_id") == "")
        | (
            pl.col("series_id").str.to_uppercase()
            != expected_id.str.to_uppercase()
            if expected_id is not None
            else pl.lit(False)
        )
        | (
            pl.col("series_id").str.slice(2, 1).str.to_uppercase()
            != pl.col("seasonal").str.strip_chars().str.to_uppercase()
            if "seasonal" in normalized.columns
            else pl.lit(False)
        )
    )
    if bad_id.height:
        row = bad_id.row(0, named=True)
        raise _fail(
            source_path,
            f"invalid series_id for requested program {program!r} at data row {row}",
        )
    if normalized.get_column("series_id").is_duplicated().any():
        duplicate_id = normalized.filter(pl.col("series_id").is_duplicated()).get_column("series_id")[0]
        raise _fail(source_path, f"duplicate series_id {duplicate_id!r} within program {program!r}")

    bad_title = normalized.filter(
        pl.col("series_title").is_null() | (pl.col("series_title").str.strip_chars() == "")
    )
    if bad_title.height:
        raise _fail(source_path, "missing or whitespace-only series_title")

    for name in ("begin_year", "end_year"):
        values = normalized.get_column(name)
        invalid = values.filter((values != "") & ~values.str.contains(_YEAR_RE.pattern))
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

    _validate_period(source_path, normalized.get_column("begin_period"), program)
    _validate_period(source_path, normalized.get_column("end_period"), program)
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
