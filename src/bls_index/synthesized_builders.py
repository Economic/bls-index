"""Local, fixture-bounded builders for series without native source titles.

This module implements only the observed PR source contract. It neither downloads
inputs nor writes/publishes artifacts.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

import polars as pl

from bls_index.http_source import DownloadRecord, InputSet
from bls_index.native_builders import (
    CANONICAL_SCHEMA,
    SCHEMA_VERSION,
    NativeSeriesError,
    _copy_to_snapshot,
    _sha256_file,
    _validate_period,
)

PR_SERIES_HEADER = (
    "series_id", "sector_code", "class_code", "measure_code", "duration_code",
    "seasonal", "base_year", "footnote_codes", "begin_year", "begin_period",
    "end_year", "end_period",
)
PR_LOOKUP_HEADERS: dict[str, tuple[str, ...]] = {
    "pr.sector": ("sector_code", "sector_name", "display_level", "selectable", "sort_sequence"),
    "pr.class": ("class_code", "class_text", "display_level", "selectable", "sort_sequence"),
    "pr.measure": ("measure_code", "measure_text", "display_level", "selectable", "sort_sequence"),
    "pr.duration": ("duration_code", "duration_text", "display_level", "selectable", "sort_sequence"),
    "pr.seasonal": ("Seasonal_code", "Seasonal_text"),
}
PR_INPUT_NAMES = ("pr.series", *PR_LOOKUP_HEADERS)
PR_TITLE_TEMPLATE = "Measure: {measure}; Sector: {sector}; Class: {class}; Duration: {duration}"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_YEAR_RE = re.compile(r"^[0-9]{4}$")
_PR_ID_RE = re.compile(r"^PR[SU][0-9]{8}$", re.IGNORECASE)
_INDEX_BASE_RE = re.compile(r"Index\s*\(\s*([0-9]{4})\s*=\s*100\s*\)", re.IGNORECASE)
_SEASONAL_CANONICAL = {"Seasonal Adjusted": "SA", "Not Seasonally Adjusted": "NSA"}


class SynthesizedSeriesError(ValueError):
    """A PR source file or verified PR input set violates its observed contract."""


def _error(path: Path | str, message: str, line: int | None = None) -> SynthesizedSeriesError:
    where = f" line {line}" if line is not None else ""
    return SynthesizedSeriesError(f"{path}{where}: {message}")


def _decode_table(path: Path, expected_header: tuple[str, ...], *, trailing_blank_rows: bool = False) -> list[dict[str, str]]:
    """Read a strict UTF-8 tab-separated file with an exact ordered header and width."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise _error(path, f"cannot read source: {exc}") from exc
    if not raw:
        raise _error(path, "source is empty; expected a header")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise _error(path, "source is not valid UTF-8") from exc

    # Accept LF and CRLF, but not bare carriage returns. A final line terminator is
    # ordinary file framing; additional empty rows are rejected except for the
    # observed trailing blank line in pr.seasonal.
    if "\r" in text.replace("\r\n", ""):
        raise _error(path, "bare carriage return is not a supported line ending")
    lines = text.splitlines()
    if trailing_blank_rows and lines and lines[-1] == "":
        lines.pop()
    if not lines:
        raise _error(path, "source is empty; expected a header")

    header = tuple(field.strip() for field in lines[0].split("\t"))
    if header != expected_header:
        raise _error(path, f"unexpected header; expected {expected_header!r}, got {header!r}", 1)
    rows: list[dict[str, str]] = []
    for line_number, line in enumerate(lines[1:], start=2):
        if not line:
            raise _error(path, "blank lines are not allowed", line_number)
        fields = line.split("\t")
        if len(fields) != len(expected_header):
            raise _error(
                path,
                f"row has {len(fields)} tab-separated fields; expected {len(expected_header)}",
                line_number,
            )
        if any(unicodedata.category(char) == "Cc" for field in fields for char in field):
            raise _error(path, "control characters are not allowed in source fields", line_number)
        rows.append(dict(zip(expected_header, fields, strict=True)))
    if not rows:
        raise _error(path, "source has a header but no data rows")
    return rows


def _lookup(path: Path, header: tuple[str, ...], key_column: str, label_column: str) -> dict[str, str]:
    rows = _decode_table(path, header, trailing_blank_rows=path.name == "pr.seasonal")
    result: dict[str, str] = {}
    for line_number, row in enumerate(rows, start=2):
        key = row[key_column].strip()
        label = row[label_column].strip()
        if not key:
            raise _error(path, f"blank lookup key in {key_column!r}", line_number)
        if key in result:
            raise _error(path, f"duplicate trimmed lookup key {key!r} in {key_column!r}", line_number)
        if not label:
            raise _error(path, f"blank lookup label in {label_column!r} for key {key!r}", line_number)
        result[key] = label
    return result


def _parse_pr_snapshot(snapshots: Mapping[str, Path], diagnostic: Path) -> pl.DataFrame:
    series_rows = _decode_table(snapshots["pr.series"], PR_SERIES_HEADER)
    lookups = {
        "sector": _lookup(snapshots["pr.sector"], PR_LOOKUP_HEADERS["pr.sector"], "sector_code", "sector_name"),
        "class": _lookup(snapshots["pr.class"], PR_LOOKUP_HEADERS["pr.class"], "class_code", "class_text"),
        "measure": _lookup(snapshots["pr.measure"], PR_LOOKUP_HEADERS["pr.measure"], "measure_code", "measure_text"),
        "duration": _lookup(snapshots["pr.duration"], PR_LOOKUP_HEADERS["pr.duration"], "duration_code", "duration_text"),
        "seasonal": _lookup(snapshots["pr.seasonal"], PR_LOOKUP_HEADERS["pr.seasonal"], "Seasonal_code", "Seasonal_text"),
    }
    if set(lookups["seasonal"]) != {"S", "U"}:
        raise _error(snapshots["pr.seasonal"], "seasonal lookup must contain exactly the observed S and U codes")
    if lookups["seasonal"] != {"S": "Seasonal Adjusted", "U": "Not Seasonally Adjusted"}:
        raise _error(snapshots["pr.seasonal"], "seasonal lookup labels are not the verified S/U mapping")

    output: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for line_number, row in enumerate(series_rows, start=2):
        series_id = row["series_id"].strip()
        if not _PR_ID_RE.fullmatch(series_id):
            raise _error(diagnostic, f"invalid PR series_id {series_id!r}; expected observed PR[SU] plus 8 digits", line_number)
        if series_id in seen_ids:
            raise _error(diagnostic, f"duplicate trimmed series_id {series_id!r}", line_number)
        seen_ids.add(series_id)

        codes = {
            name: row[f"{name}_code"].strip()
            for name in ("sector", "class", "measure", "duration")
        }
        seasonal_code = row["seasonal"].strip()
        if not seasonal_code:
            raise _error(diagnostic, "blank required seasonal key", line_number)
        for name, code in (*codes.items(), ("seasonal", seasonal_code)):
            if not code:
                raise _error(diagnostic, f"blank required {name} lookup key", line_number)
            if code not in lookups[name]:
                if name == "seasonal":
                    raise _error(diagnostic, f"invalid, blank, or missing seasonal source code {code!r}", line_number)
                raise _error(diagnostic, f"missing {name} lookup key {code!r}", line_number)
        expected_id = "PR" + seasonal_code + "".join(codes[name] for name in ("sector", "class", "measure", "duration"))
        if series_id.upper() != expected_id.upper():
            raise _error(diagnostic, f"invalid PR series_id {series_id!r}; does not match source components", line_number)

        for name in ("begin_year", "end_year"):
            value = row[name].strip()
            if value and not _YEAR_RE.fullmatch(value):
                raise _error(diagnostic, f"invalid {name} value {value!r}; expected a four-digit year", line_number)
            if value == "0000":
                raise _error(diagnostic, f"invalid {name} value '0000'; year must be positive", line_number)
        begin = row["begin_year"].strip() or None
        end = row["end_year"].strip() or None
        if begin is not None and end is not None and int(begin) > int(end):
            raise _error(diagnostic, f"begin_year exceeds end_year for series_id {series_id!r}", line_number)
        begin_period = row["begin_period"].strip()
        end_period = row["end_period"].strip()
        try:
            _validate_period(diagnostic, pl.Series("period", [begin_period], dtype=pl.String), "pr")
            _validate_period(diagnostic, pl.Series("period", [end_period], dtype=pl.String), "pr")
        except NativeSeriesError as exc:
            raise SynthesizedSeriesError(str(exc)) from exc
        if begin_period and begin is None:
            raise _error(diagnostic, "begin_period is present while begin_year is missing", line_number)
        if end_period and end is None:
            raise _error(diagnostic, "end_period is present while end_year is missing", line_number)

        duration_label = lookups["duration"][codes["duration"]]
        index_base = _INDEX_BASE_RE.search(duration_label)
        base_year = row["base_year"].strip()
        if index_base is not None and base_year != index_base.group(1):
            raise _error(
                diagnostic,
                f"base_year {base_year!r} does not match index duration base {index_base.group(1)!r}",
                line_number,
            )

        title = PR_TITLE_TEMPLATE.format(
            measure=lookups["measure"][codes["measure"]],
            sector=lookups["sector"][codes["sector"]],
            **{"class": lookups["class"][codes["class"]]},
            duration=duration_label,
        )
        output.append({
            "program": "pr",
            "series_id": series_id,
            "series_title": title,
            "title_source": "synthesized",
            "seasonal": _SEASONAL_CANONICAL[lookups["seasonal"][seasonal_code]],
            "begin_year": int(begin) if begin is not None else None,
            "end_year": int(end) if end is not None else None,
            "end_period": end_period or None,
        })

    if len(output) != len(series_rows):
        raise _error(diagnostic, "builder did not emit exactly one output row per source row")
    return pl.DataFrame(output).cast(CANONICAL_SCHEMA)


def parse_pr_sources(sources: Mapping[str, str | Path]) -> pl.DataFrame:
    """Parse explicit local PR files keyed by their exact names, for tests and local use.

    This path-based API does not accept network URLs or fetch inputs. Each input is
    snapshotted and hash-checked, and each source path is checked before and after parsing.
    """
    if set(sources) != set(PR_INPUT_NAMES):
        raise SynthesizedSeriesError(f"PR sources must be exactly {PR_INPUT_NAMES!r}")
    paths = {name: Path(sources[name]) for name in PR_INPUT_NAMES}
    try:
        with tempfile.TemporaryDirectory(prefix="bls-index-pr-") as staging:
            root = Path(staging)
            snapshots: dict[str, Path] = {}
            digests: dict[str, str] = {}
            for name, source in paths.items():
                snapshot = root / name
                digests[name] = _copy_to_snapshot(source, snapshot)
                snapshots[name] = snapshot
                if _sha256_file(source) != digests[name]:
                    raise _error(source, "source changed while staging")
            frame = _parse_pr_snapshot(snapshots, paths["pr.series"])
            for name, source in paths.items():
                if _sha256_file(source) != digests[name]:
                    raise _error(source, "source changed while parsing")
            return frame
    except NativeSeriesError as exc:
        raise SynthesizedSeriesError(str(exc)) from exc
    except OSError as exc:
        raise _error("PR input set", f"cannot stage or clean up sources: {exc}") from exc


def _validate_input_set(input_set: InputSet) -> dict[str, DownloadRecord]:
    if input_set.program != "pr":
        raise SynthesizedSeriesError(f"InputSet program must be 'pr', got {input_set.program!r}")
    if not isinstance(input_set.attempts, int) or isinstance(input_set.attempts, bool) or input_set.attempts < 1:
        raise SynthesizedSeriesError("InputSet must record at least one verification attempt")
    if len(input_set.files) != len(PR_INPUT_NAMES) or len(input_set.rechecks) != len(PR_INPUT_NAMES):
        raise SynthesizedSeriesError(f"PR InputSet must contain exactly these inputs: {PR_INPUT_NAMES!r}")
    records: dict[str, DownloadRecord] = {}
    rechecks: dict[str, DownloadRecord] = {}
    for record in input_set.files:
        parts = [part for part in urlsplit(record.url).path.split("/") if part]
        if len(parts) < 2 or parts[-2] != "pr" or parts[-1] not in PR_INPUT_NAMES:
            raise SynthesizedSeriesError(f"unexpected PR input URL {record.url!r}")
        name = parts[-1]
        if name in records:
            raise SynthesizedSeriesError(f"duplicate PR input record for {name!r}")
        if urlsplit(record.url).scheme not in {"http", "https"} or not urlsplit(record.url).netloc:
            raise SynthesizedSeriesError(f"input record URL must be HTTP(S): {record.url!r}")
        if record.status != 200 or not isinstance(record.bytes, int) or isinstance(record.bytes, bool) or record.bytes < 0:
            raise SynthesizedSeriesError(f"invalid successful response metadata for {record.url!r}")
        if not isinstance(record.sha256, str) or not _SHA256_RE.fullmatch(record.sha256):
            raise SynthesizedSeriesError(f"invalid SHA-256 for {record.url!r}")
        if record.path is None:
            raise SynthesizedSeriesError(f"PR input {name!r} has no local downloaded path")
        records[name] = record
    for record in input_set.rechecks:
        parts = [part for part in urlsplit(record.url).path.split("/") if part]
        name = parts[-1] if len(parts) >= 2 and parts[-2] == "pr" else ""
        if name not in PR_INPUT_NAMES or name in rechecks:
            raise SynthesizedSeriesError(f"unexpected or duplicate PR recheck URL {record.url!r}")
        if record.status != 200 or not isinstance(record.bytes, int) or isinstance(record.bytes, bool) or record.bytes < 0:
            raise SynthesizedSeriesError(f"invalid successful recheck metadata for {record.url!r}")
        if not isinstance(record.sha256, str) or not _SHA256_RE.fullmatch(record.sha256):
            raise SynthesizedSeriesError(f"invalid recheck SHA-256 for {record.url!r}")
        rechecks[name] = record
    if set(records) != set(PR_INPUT_NAMES) or set(rechecks) != set(PR_INPUT_NAMES):
        raise SynthesizedSeriesError(f"PR InputSet names must be exactly {PR_INPUT_NAMES!r}")
    for name in PR_INPUT_NAMES:
        record, recheck = records[name], rechecks[name]
        if record.url != recheck.url or record.sha256 != recheck.sha256 or record.bytes != recheck.bytes:
            raise SynthesizedSeriesError(f"download recheck does not match input record for {name!r}")
    return records


def parse_pr_input_set(input_set: InputSet) -> pl.DataFrame:
    """Build canonical PR rows from one previously verified HTTP ``InputSet``.

    No request is made. Download metadata and both actual file reads are revalidated;
    the exact verified snapshots are the only bytes parsed.
    """
    records = _validate_input_set(input_set)
    paths = {name: Path(record.path) for name, record in records.items() if record.path is not None}
    try:
        with tempfile.TemporaryDirectory(prefix="bls-index-pr-verified-") as staging:
            root = Path(staging)
            snapshots: dict[str, Path] = {}
            digests: dict[str, str] = {}
            for name in PR_INPUT_NAMES:
                record = records[name]
                source = paths[name]
                snapshot = root / name
                digest = _copy_to_snapshot(source, snapshot)
                size = snapshot.stat().st_size
                if digest != record.sha256 or size != record.bytes:
                    raise _error(source, "input snapshot changed or disagrees with verified provenance")
                if _sha256_file(source) != record.sha256:
                    raise _error(source, "input changed while staging")
                snapshots[name] = snapshot
                digests[name] = digest
            frame = _parse_pr_snapshot(snapshots, paths["pr.series"])
            for name, source in paths.items():
                actual = _sha256_file(source)
                if actual != digests[name] or source.stat().st_size != records[name].bytes:
                    raise _error(source, "input changed while parsing")
            if frame.schema != CANONICAL_SCHEMA or frame.height != len(_decode_table(snapshots["pr.series"], PR_SERIES_HEADER)):
                raise _error(paths["pr.series"], f"builder output violates canonical schema v{SCHEMA_VERSION} or row count")
            return frame
    except NativeSeriesError as exc:
        raise SynthesizedSeriesError(str(exc)) from exc
    except OSError as exc:
        raise _error("PR InputSet", f"cannot stage or clean up sources: {exc}") from exc
