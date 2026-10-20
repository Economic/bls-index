"""Build one program's catalog rows from its downloaded source files."""

from __future__ import annotations

import logging
import string
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from bls_index.schema import BuildError, canonical_rows, read_tsv
from bls_index.scope import NATIVE_TITLE_PROGRAMS

log = logging.getLogger(__name__)

ROW_COLUMNS = ("series_id", "begin_year", "end_year", "end_period")


@dataclass(frozen=True)
class Synthesis:
    """How a program without native titles builds them from lookup files.

    Each lookup ``<program>.<dimension>`` is joined on ``<dimension>_code`` and supplies
    the label column named here. The series ID must equal the program code, the seasonal
    code, and ``id_codes`` concatenated, so the codes that choose the title are the codes
    the ID encodes.
    """

    labels: Mapping[str, str]  # dimension -> label column in its lookup file
    id_codes: tuple[str, ...]
    template: str


SYNTHESES: dict[str, Synthesis] = {
    "pr": Synthesis(
        labels={"sector": "sector_name", "class": "class_text", "measure": "measure_text",
                "duration": "duration_text"},
        id_codes=("sector_code", "class_code", "measure_code", "duration_code"),
        template="Measure: {measure}; Sector: {sector}; Class: {class}; Duration: {duration}",
    ),
    "sm": Synthesis(
        labels={"state": "state_name", "area": "area_name", "supersector": "supersector_name",
                "industry": "industry_name", "data_type": "data_type_text"},
        id_codes=("state_code", "area_code", "industry_code", "data_type_code"),
        template=("Data type: {data_type}; State: {state}; Area: {area}; "
                  "Supersector: {supersector}; Industry: {industry}"),
    ),
    "jt": Synthesis(
        labels={"industry": "industry_text", "state": "state_text", "area": "area_text",
                "sizeclass": "sizeclass_text", "dataelement": "dataelement_text",
                "ratelevel": "ratelevel_text"},
        id_codes=("industry_code", "state_code", "area_code", "sizeclass_code",
                  "dataelement_code", "ratelevel_code"),
        template=("Data element: {dataelement}; Rate/level: {ratelevel}; Industry: {industry}; "
                  "State: {state}; Area: {area}; Size class: {sizeclass}"),
    ),
}  # fmt: skip


def build_program(program: str, files: Mapping[str, Path]) -> pl.DataFrame:
    """Return canonical rows for ``program`` from local files keyed by file name."""
    if program in NATIVE_TITLE_PROGRAMS:
        return parse_native_series(files[f"{program}.series"], program)
    if program in SYNTHESES:
        return synthesize(program, files)
    raise BuildError(f"no builder for program {program!r}")


def parse_native_series(path: Path, program: str) -> pl.DataFrame:
    """Parse a ``.series`` file that carries its own ``series_title`` column."""
    path = Path(path)
    frame = read_tsv(path, ("series_title", *ROW_COLUMNS), optional=("seasonal",))
    return canonical_rows(frame, program, "native", str(path))


def synthesize(program: str, files: Mapping[str, Path]) -> pl.DataFrame:
    """Build titles by joining ``.series`` to each lookup file and filling a template."""
    spec = SYNTHESES[program]
    where = str(files[f"{program}.series"])
    keys = [f"{dimension}_code" for dimension in spec.labels]
    extra = ["base_year"] if program == "pr" else []
    series = read_tsv(files[f"{program}.series"], (*ROW_COLUMNS, "seasonal", *keys, *extra))
    series = series.with_columns(pl.col(key).str.strip_chars() for key in [*keys, "seasonal"])
    rows = series.height

    for dimension, label in spec.labels.items():
        key = f"{dimension}_code"
        lookup_path = files[f"{program}.{dimension}"]
        lookup = read_tsv(lookup_path, (key, label)).select(
            pl.col(key).str.strip_chars(), pl.col(label).str.strip_chars().alias(dimension)
        )
        if lookup.select(pl.col(key).is_null().any() | (pl.col(key) == "").any()).item():
            raise BuildError(f"{lookup_path}: blank lookup key")
        duplicate = lookup.filter(pl.col(key).is_duplicated())
        if duplicate.height:
            raise BuildError(f"{lookup_path}: duplicate lookup key {duplicate[key][0]!r}")
        if lookup.select(pl.col(dimension).is_null().any() | (pl.col(dimension) == "").any()).item():
            raise BuildError(f"{lookup_path}: blank label in {label!r}")
        unmatched = series.join(lookup, on=key, how="anti")
        if unmatched.height:
            raise BuildError(f"{where}: {key} {unmatched[key][0]!r} is not in {lookup_path.name}")
        series = series.join(lookup, on=key, how="left", maintain_order="left")

    expected_id = pl.concat_str([pl.lit(program.upper()), pl.col("seasonal"), *spec.id_codes])
    mismatch = series.filter(
        (pl.col("series_id").str.strip_chars().str.to_uppercase() != expected_id.str.to_uppercase())
        .fill_null(True)
    )
    if mismatch.height:
        raise BuildError(
            f"{where}: series_id {mismatch['series_id'][0]!r} does not match its dimension codes"
        )
    if program == "sm":
        bad = series.filter(pl.col("supersector_code") != pl.col("industry_code").str.slice(0, 2))
        if bad.height:
            raise BuildError(f"{where}: supersector_code does not match industry_code prefix "
                             f"for {bad['series_id'][0]!r}")
    if program == "pr":
        base = pl.col("duration").str.extract(r"(?i)Index\s*\(\s*([0-9]{4})\s*=\s*100\s*\)", 1)
        differs = (base != pl.col("base_year").str.strip_chars()).fill_null(True)
        count = series.filter(base.is_not_null() & differs).height
        if count:
            log.warning("%s: %d rows whose base_year differs from the duration's index base", where, count)

    series = series.with_columns(series_title=_fill(spec.template))
    if series.height != rows:
        raise BuildError(f"{where}: built {series.height} rows from {rows} source rows")
    return canonical_rows(series, program, "synthesized", where)


def _fill(template: str) -> pl.Expr:
    parts: list[pl.Expr] = []
    for literal, field, _, _ in string.Formatter().parse(template):
        if literal:
            parts.append(pl.lit(literal))
        if field:
            parts.append(pl.col(field))
    return pl.concat_str(parts)
