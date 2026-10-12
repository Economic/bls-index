from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from bls_index.native_builders import (
    CANONICAL_SCHEMA,
    NativeSeriesError,
    SOURCE_HEADERS,
    SUPPORTED_NATIVE_PROGRAMS,
    parse_native_series,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "native"


def test_supported_program_headers_are_explicit_and_differ_by_program():
    assert SUPPORTED_NATIVE_PROGRAMS == ("ap", "ce", "cu", "ln", "oe")
    assert SOURCE_HEADERS["ap"] != SOURCE_HEADERS["ce"]
    assert "seasonal" not in SOURCE_HEADERS["ap"]
    assert "series_title" in SOURCE_HEADERS["oe"]


@pytest.mark.parametrize("program", SUPPORTED_NATIVE_PROGRAMS)
def test_native_fixtures_parse_to_exact_schema(program):
    frame = parse_native_series(FIXTURE_DIR / f"{program}.series", program)
    assert frame.schema == CANONICAL_SCHEMA
    assert frame.height > 0
    assert frame.get_column("program").unique().to_list() == [program]
    assert frame.get_column("title_source").unique().to_list() == ["native"]


def test_native_titles_are_preserved_verbatim_and_duplicates_are_allowed():
    frame = parse_native_series(FIXTURE_DIR / "ap.series", "ap")
    titles = frame.get_column("series_title").to_list()
    assert titles == [
        "  Native title with punctuation — and spaces  ",
        "  Native title with punctuation — and spaces  ",
    ]
    assert frame.get_column("series_title").is_duplicated().all()
    assert frame.get_column("series_id").to_list() == ["X0001", "X0002"]
    assert frame.get_column("seasonal").to_list() == ["unknown", "unknown"]
    assert frame.get_column("begin_year").to_list() == [1980, None]
    assert frame.get_column("end_period").to_list() == ["M08", None]


def test_seasonal_and_period_fields_are_normalized():
    ce = parse_native_series(FIXTURE_DIR / "ce.series", "ce")
    assert ce.get_column("seasonal").to_list() == ["SA", "NSA"]
    oe = parse_native_series(FIXTURE_DIR / "oe.series", "oe")
    assert oe.get_column("end_period").to_list() == ["A01"]
    assert oe.get_column("begin_year").to_list() == [1997]


def _write(tmp_path: Path, content: bytes, filename: str = "input.series") -> Path:
    path = tmp_path / filename
    path.write_bytes(content)
    return path


def _ap(body: str) -> bytes:
    return ("\t".join(SOURCE_HEADERS["ap"]) + "\n" + body).encode("utf-8")


def _valid_ap_row(
    *, sid: str = "AP0001", title: str = "A title", begin: str = "1980",
    bp: str = "M01", end: str = "2026", ep: str = "M08",
) -> str:
    return "\t".join([sid, "0000", "000001", title, "", begin, bp, end, ep]) + "\n"


def test_schema_drift_and_row_width_are_rejected(tmp_path):
    wrong_header = _write(tmp_path, b"series_id\tseries_title\nX1\tT\n")
    with pytest.raises(NativeSeriesError, match="unexpected 'ap' header"):
        parse_native_series(wrong_header, "ap")

    too_wide = _write(tmp_path, _ap("AP0001\t0000\t1\tTitle\t\t1980\tM01\t2026\tM08\textra\n"))
    with pytest.raises(NativeSeriesError, match="expected 9"):
        parse_native_series(too_wide, "ap")


def test_series_ids_trim_but_must_be_nonempty_valid_and_unique(tmp_path):
    duplicate = _write(
        tmp_path,
        _ap(_valid_ap_row(sid="AP1  ") + _valid_ap_row(sid="  AP1")),
    )
    with pytest.raises(NativeSeriesError, match="duplicate series_id"):
        parse_native_series(duplicate, "ap")

    empty_id = _write(tmp_path, _ap(_valid_ap_row(sid="   ")))
    with pytest.raises(NativeSeriesError, match="invalid series_id"):
        parse_native_series(empty_id, "ap")

    invalid_id = _write(tmp_path, _ap(_valid_ap_row(sid="AP-1")))
    with pytest.raises(NativeSeriesError, match="invalid series_id"):
        parse_native_series(invalid_id, "ap")


def test_titles_must_be_nonblank_but_keep_original_spacing(tmp_path):
    whitespace = _write(tmp_path, _ap(_valid_ap_row(title="   ")))
    with pytest.raises(NativeSeriesError, match="whitespace-only series_title"):
        parse_native_series(whitespace, "ap")

    preserved = _write(tmp_path, _ap(_valid_ap_row(title=" title ")))
    assert parse_native_series(preserved, "ap").get_column("series_title").item() == " title "


def test_invalid_missing_seasonal_code_is_rejected(tmp_path):
    header = "\t".join(SOURCE_HEADERS["ce"])
    row = "\t".join(["CES1", "00", "000000", "01", "", "title", "", "2001", "M01", "2026", "M08"])
    path = _write(tmp_path, f"{header}\n{row}\n".encode())
    with pytest.raises(NativeSeriesError, match="invalid or missing seasonal"):
        parse_native_series(path, "ce")

    row_fields = row.split("\t")
    row_fields[4] = "X"
    path = _write(tmp_path, f"{header}\n{'\t'.join(row_fields)}\n".encode())
    with pytest.raises(NativeSeriesError, match="invalid or missing seasonal"):
        parse_native_series(path, "ce")


@pytest.mark.parametrize(
    ("begin", "end", "period", "message"),
    [
        ("80", "2026", "M08", "four-digit year"),
        ("0000", "2026", "M08", "year must be positive"),
        ("2027", "2026", "M08", "begin_year exceeds end_year"),
        ("1980", "2026", "M14", "invalid period code"),
        ("1980", "2026", "X01", "invalid period code"),
    ],
)
def test_invalid_year_or_period_metadata_fails_closed(tmp_path, begin, end, period, message):
    path = _write(tmp_path, _ap(_valid_ap_row(begin=begin, end=end, ep=period)))
    with pytest.raises(NativeSeriesError, match=message):
        parse_native_series(path, "ap")


def test_end_period_without_end_year_is_rejected(tmp_path):
    path = _write(tmp_path, _ap(_valid_ap_row(end="", ep="M08")))
    with pytest.raises(NativeSeriesError, match="end_period is present while end_year is missing"):
        parse_native_series(path, "ap")


def test_invalid_utf8_and_control_text_are_rejected(tmp_path):
    invalid_utf8 = _write(tmp_path, _ap(_valid_ap_row()).replace(b"A title", b"A \xff title"))
    with pytest.raises(NativeSeriesError, match="not valid UTF-8"):
        parse_native_series(invalid_utf8, "ap")

    control = _write(tmp_path, _ap(_valid_ap_row(title="bad\x01title")))
    with pytest.raises(NativeSeriesError, match="control characters"):
        parse_native_series(control, "ap")


def test_empty_file_blank_row_and_empty_row_are_rejected(tmp_path):
    empty = _write(tmp_path, b"")
    with pytest.raises(NativeSeriesError, match="source is empty"):
        parse_native_series(empty, "ap")

    header_only = _write(tmp_path, ("\t".join(SOURCE_HEADERS["ap"]) + "\n").encode())
    with pytest.raises(NativeSeriesError, match="no data rows"):
        parse_native_series(header_only, "ap")

    blank = _write(tmp_path, _ap("\n"))
    with pytest.raises(NativeSeriesError, match="blank lines"):
        parse_native_series(blank, "ap")

    empty_fields = _write(tmp_path, _ap("\t" * 8 + "\n"))
    with pytest.raises(NativeSeriesError, match="empty data row"):
        parse_native_series(empty_fields, "ap")


def test_header_padding_is_allowed_but_not_column_drift(tmp_path):
    header = list(SOURCE_HEADERS["ap"])
    header[0] = " series_id  "
    allowed = _write(tmp_path, ("\t".join(header) + "\n" + _valid_ap_row() ).encode())
    assert parse_native_series(allowed, "ap").height == 1

    header[1] = "different_code"
    drift = _write(tmp_path, ("\t".join(header) + "\n" + _valid_ap_row()).encode())
    with pytest.raises(NativeSeriesError, match="unexpected 'ap' header"):
        parse_native_series(drift, "ap")


def test_program_must_be_explicit_and_supported(tmp_path):
    with pytest.raises(NativeSeriesError, match="unsupported native program"):
        parse_native_series(tmp_path / "does-not-exist.series", "bd")
