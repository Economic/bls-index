from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from bls_index.native_builders import (
    CANONICAL_SCHEMA,
    NativeSeriesError,
    SOURCE_HEADERS,
    SERIES_ID_COMPONENTS,
    SERIES_ID_FIELD_SLICES,
    SUPPORTED_NATIVE_PROGRAMS,
    parse_native_series,
    valid_series_id,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "native"


def test_supported_program_headers_are_explicit_and_differ_by_program():
    assert len(SUPPORTED_NATIVE_PROGRAMS) == 30
    assert SOURCE_HEADERS["ap"] != SOURCE_HEADERS["ce"]
    assert "seasonal" not in SOURCE_HEADERS["ap"]
    assert "series_title" in SOURCE_HEADERS["oe"]


@pytest.mark.parametrize("program", ("ap", "ce", "cu", "ln", "oe"))
def test_original_native_fixtures_parse_to_exact_schema(program):
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
    assert frame.get_column("series_id").to_list() == ["APU0000000001", "APU0000000002"]
    assert frame.get_column("seasonal").to_list() == ["unknown", "unknown"]
    assert frame.get_column("begin_year").to_list() == [1980, None]
    assert frame.get_column("end_period").to_list() == ["M08", "M12"]


def test_seasonal_and_period_fields_are_normalized():
    ce = parse_native_series(FIXTURE_DIR / "ce.series", "ce")
    assert ce.get_column("seasonal").to_list() == ["SA", "NSA"]
    assert ce.get_column("series_id").to_list() == ["CES0000000001", "CEU0000000002"]
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
    *, sid: str = "APU0000000001", title: str = "A title", begin: str = "1980",
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
        _ap(_valid_ap_row(sid="APU0000000001  ") + _valid_ap_row(sid="  APU0000000001")),
    )
    with pytest.raises(NativeSeriesError, match="duplicate series_id"):
        parse_native_series(duplicate, "ap")

    empty_id = _write(tmp_path, _ap(_valid_ap_row(sid="   ")))
    with pytest.raises(NativeSeriesError, match="invalid series_id"):
        parse_native_series(empty_id, "ap")

    invalid_id = _write(tmp_path, _ap(_valid_ap_row(sid="AP/1")))
    with pytest.raises(NativeSeriesError, match="invalid series_id"):
        parse_native_series(invalid_id, "ap")

    wrong_program_id = _write(tmp_path, _ap(_valid_ap_row(sid="CES0000000001")))
    with pytest.raises(NativeSeriesError, match="requested program 'ap'"):
        parse_native_series(wrong_program_id, "ap")


def test_titles_must_be_nonblank_but_keep_original_spacing(tmp_path):
    whitespace = _write(tmp_path, _ap(_valid_ap_row(title="   ")))
    with pytest.raises(NativeSeriesError, match="whitespace-only series_title"):
        parse_native_series(whitespace, "ap")

    preserved = _write(tmp_path, _ap(_valid_ap_row(title=" title ")))
    assert parse_native_series(preserved, "ap").get_column("series_title").item() == " title "


def test_invalid_missing_seasonal_code_is_rejected(tmp_path):
    header = "\t".join(SOURCE_HEADERS["ce"])
    rows = [
        ["CES0000000001", "00", "000000", "01", "", "title", "", "2001", "M01", "2026", "M08"],
        ["CES0000000001", "00", "000000", "01", "X", "title", "", "2001", "M01", "2026", "M08"],
    ]
    body = "".join("\t".join(row) + "\n" for row in rows)
    path = _write(tmp_path, f"{header}\n{body}".encode())
    with pytest.raises(NativeSeriesError, match=r"invalid, blank, or missing seasonal.*'X'"):
        parse_native_series(path, "ce")


def test_source_mutation_after_staging_is_rejected(monkeypatch, tmp_path):
    import bls_index.native_builders as native_builders

    path = _write(tmp_path, _ap(_valid_ap_row(title="snapshot title")))
    parse_snapshot = native_builders._parse_snapshot

    def mutate_source_before_parse(snapshot, source_path, program):
        # Keep the exact row shape and header, but change bytes after private staging.
        path.write_bytes(_ap(_valid_ap_row(title="modified title")))
        return parse_snapshot(snapshot, source_path, program)

    monkeypatch.setattr(native_builders, "_parse_snapshot", mutate_source_before_parse)
    with pytest.raises(NativeSeriesError, match="source changed while parsing"):
        parse_native_series(path, "ap")


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


@pytest.mark.parametrize("program", ("cu", "cw"))
@pytest.mark.parametrize("period", ("M12", "S01", "S02", "S03"))
def test_cpi_programs_accept_documented_periods(
    tmp_path, program, period
):
    path = _constructed_program_file(tmp_path, program, end_period=period)
    frame = parse_native_series(path, program)
    assert frame.get_column("end_period").item() == period


@pytest.mark.parametrize(
    ("program", "period"),
    [("cu", "S04"), ("cw", "S04"),
     ("cu", "Q01"), ("cw", "Q01"), ("cu", "A01"), ("cw", "A01"),
     ("su", "S01")],
)
def test_semiannual_periods_are_restricted_to_documented_cpi_programs(
    tmp_path, program, period
):
    path = _constructed_program_file(tmp_path, program, end_period=period)
    with pytest.raises(NativeSeriesError, match="invalid period code"):
        parse_native_series(path, program)


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
        parse_native_series(tmp_path / "does-not-exist.series", "zz")


def test_program_specific_prefixes_and_documented_id_separators():
    from bls_index.native_builders import SERIES_ID_PREFIXES, valid_series_id

    assert set(SERIES_ID_PREFIXES) == set(SUPPORTED_NATIVE_PROGRAMS) | {"sm", "jt", "pr"}
    assert valid_series_id("IPUAN1111__L010000000", "ip")
    assert valid_series_id("NDU332710332710S", "nd")
    assert valid_series_id("NDUBRSM--BRSM--", "nd")
    assert valid_series_id("PCU1133--1133--", "pc")
    assert not valid_series_id("CES0000000001", "ap")
    assert not valid_series_id("AP-", "ap")
    assert not valid_series_id("CE", "ce")
    assert not valid_series_id("CES_____", "ce")
    assert valid_series_id("APU000070111", "ap")
    assert not valid_series_id("APU00007011111", "ap")
    assert valid_series_id("CES0000000001", "ce")
    assert not valid_series_id("CES____00001", "ce")
    assert valid_series_id("APU0000000001", "ap")
    assert not valid_series_id("APU00007011", "ap")


def _constructed_program_file(
    tmp_path: Path,
    program: str,
    seasonal: str | None = None,
    end_period: str | None = None,
) -> Path:
    """Write one tiny constructed row; this is not a BLS sample row."""
    source_lines = (Path(__file__).parent / "fixtures" / "real_native" / f"{program}.series").read_text().splitlines()
    header = [field.strip() for field in source_lines[0].split("\t")]
    row = dict(zip(header, source_lines[1].split("\t"), strict=True))
    row["series_title"] = "Constructed native-title adapter fixture"
    if seasonal is not None:
        row["seasonal"] = seasonal
        row["series_id"] = row["series_id"].strip()[:2] + seasonal + row["series_id"].strip()[3:]
    if program == "kv":
        # The current observed KV header has date columns; blank source dates become null.
        for name in ("begin_year", "begin_period", "end_year", "end_period"):
            row[name] = ""
    if end_period is not None:
        row["end_period"] = end_period
    content = "\t".join(header) + "\n" + "\t".join(row[name] for name in header) + "\n"
    return _write(tmp_path, content.encode("utf-8"), filename=f"{program}.series")


def test_supported_programs_match_observed_probe_headers_and_widths():
    report = json.loads(Path("docs/evidence/2026-10-07-local-source-probe.json").read_text())
    assert len(SUPPORTED_NATIVE_PROGRAMS) == 30
    assert set(SOURCE_HEADERS) == set(SUPPORTED_NATIVE_PROGRAMS)
    assert set(SOURCE_HEADERS).issubset(report["programs"])
    for program in SUPPORTED_NATIVE_PROGRAMS:
        entry = report["programs"][program]
        series_file = next(
            item for item in entry["files"] if item["url"].endswith(f"/{program}.series")
        )
        layout = series_file["layout"]
        assert tuple(layout["header_columns"]) == SOURCE_HEADERS[program]
        assert layout["rows_with_header_width"] == layout["rows"]
        assert set(layout["field_count_histogram"]) == {str(len(SOURCE_HEADERS[program]))}


@pytest.mark.parametrize("program", SUPPORTED_NATIVE_PROGRAMS)
def test_all_native_adapters_parse_constructed_compact_rows(tmp_path, program):
    path = _constructed_program_file(tmp_path, program)
    frame = parse_native_series(path, program)
    assert frame.schema == CANONICAL_SCHEMA
    assert frame.height == 1
    assert frame.get_column("program").item() == program
    assert frame.get_column("series_id").item() == path.read_text().splitlines()[1].split("\t")[0].strip()
    assert frame.get_column("series_title").item() == "Constructed native-title adapter fixture"
    assert frame.get_column("title_source").item() == "native"
    if program == "kv":
        assert frame.get_column("begin_year").item() is None
        assert frame.get_column("end_year").item() is None
        assert frame.get_column("end_period").item() is None
    if program in {"ap", "mp"}:
        assert frame.get_column("seasonal").item() == "unknown"
    if program == "cx":
        assert frame.get_column("seasonal").item() == "NSA"


@pytest.mark.parametrize(
    ("program", "field"),
    [
        ("cu", "area_code"), ("cw", "item_code"), ("su", "area_code"),
        ("wd", "group_code"), ("wp", "group_code"),
        ("nd", "industry_code"), ("pc", "product_code"),
        ("cx", "item_code"), ("oe", "area_code"), ("la", "measure_code"),
        ("ep", "occ_code"), ("ep", "ind_code"),
        ("is", "supersector_code"), ("is", "industry_code"),
        ("is", "data_type_code"), ("is", "case_type_code"), ("is", "area_code"),
        ("mp", "sector_code"), ("mp", "measure_code"), ("mp", "duration_code"),
        ("ws", "measure_code"),
    ],
)
def test_documented_id_dimensions_must_match_source_columns(tmp_path, program, field):
    path = _constructed_program_file(tmp_path, program)
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    row = lines[1].split("\t")
    original = row[header.index(field)]
    changed = ("Z" if not original.startswith("Z") else "Y") + original[1:]
    row[header.index(field)] = changed
    path.write_text("\n".join([lines[0], "\t".join(row), ""]), encoding="utf-8")
    with pytest.raises(NativeSeriesError, match="invalid series_id"):
        parse_native_series(path, program)


@pytest.mark.parametrize(
    ("program", "field"),
    [
        (program, field)
        for program, slices in SERIES_ID_FIELD_SLICES.items()
        for field, _offset, _width, _source_width in slices
    ],
)
def test_verified_partial_id_field_mismatches_are_rejected(tmp_path, program, field):
    path = _constructed_program_file(tmp_path, program)
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    row = lines[1].split("\t")
    original = row[header.index(field)]
    changed_prefix = "Z" if not original.strip().upper().startswith("Z") else "Y"
    row[header.index(field)] = changed_prefix + original[1:]
    path.write_text("\n".join([lines[0], "\t".join(row), ""]), encoding="utf-8")
    with pytest.raises(NativeSeriesError, match="invalid series_id"):
        parse_native_series(path, program)


def test_ei_unlisted_id_position_is_opaque_when_verified_slice_matches(tmp_path):
    path = _constructed_program_file(tmp_path, "ei")
    lines = path.read_text(encoding="utf-8").splitlines()
    row = lines[1].split("\t")
    original_id = row[0]
    changed_character = "Z" if original_id[5] != "Z" else "Y"
    row[0] = original_id[:5] + changed_character + original_id[6:]
    path.write_text("\n".join([lines[0], "\t".join(row), ""]), encoding="utf-8")

    parsed = parse_native_series(path, "ei")
    assert parsed.get_column("series_id").item() == row[0].strip()


@pytest.mark.parametrize(
    ("program", "field"), [("ei", "series_name"), ("nb", "survey_code")]
)
def test_partial_id_mappings_leave_unlisted_source_fields_opaque(tmp_path, program, field):
    path = _constructed_program_file(tmp_path, program)
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    row = lines[1].split("\t")
    row[header.index(field)] = "changed unlisted source value"
    path.write_text("\n".join([lines[0], "\t".join(row), ""]), encoding="utf-8")

    parsed = parse_native_series(path, program)
    assert parsed.get_column("series_id").item() == row[0].strip()


@pytest.mark.parametrize(
    ("program", "field"),
    [
        (program, field)
        for program, components in SERIES_ID_COMPONENTS.items()
        for field in components
        if field in SOURCE_HEADERS[program]
        and field != "seasonal"
    ],
)
def test_whitespace_only_id_components_are_rejected(tmp_path, program, field):
    path = _constructed_program_file(tmp_path, program)
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    row = lines[1].split("\t")
    row[header.index(field)] = "   "
    path.write_text("\n".join([lines[0], "\t".join(row), ""]), encoding="utf-8")
    with pytest.raises(NativeSeriesError, match="invalid series_id"):
        parse_native_series(path, program)


@pytest.mark.parametrize(
    ("program", "field"),
    [
        (program, field)
        for program in ("ep", "is", "mp", "ws")
        for field in SERIES_ID_COMPONENTS[program]
        if field in SOURCE_HEADERS[program]
    ],
)
def test_blank_newly_mapped_id_components_are_rejected(tmp_path, program, field):
    path = _constructed_program_file(tmp_path, program)
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    row = lines[1].split("\t")
    row[header.index(field)] = ""
    path.write_text("\n".join([lines[0], "\t".join(row), ""]), encoding="utf-8")
    with pytest.raises(NativeSeriesError, match="invalid series_id|invalid, blank, or missing seasonal"):
        parse_native_series(path, program)


def test_blank_cu_area_component_is_rejected(tmp_path):
    path = _constructed_program_file(tmp_path, "cu")
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    row = lines[1].split("\t")
    row[header.index("area_code")] = ""
    path.write_text("\n".join([lines[0], "\t".join(row), ""]), encoding="utf-8")
    with pytest.raises(NativeSeriesError, match="invalid series_id"):
        parse_native_series(path, "cu")


def test_wp_dash_item_sentinel_remains_valid(tmp_path):
    path = _constructed_program_file(tmp_path, "wp")
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    row = lines[1].split("\t")
    row[0] = "WPS01"
    row[header.index("group_code")] = "01"
    row[header.index("item_code")] = "-"
    path.write_text("\n".join([lines[0], "\t".join(row), ""]), encoding="utf-8")
    assert parse_native_series(path, "wp").height == 1


@pytest.mark.parametrize("program", (
    "cu", "cw", "su", "wd", "wp", "nd", "pc", "cx", "oe", "la",
    "ep", "is", "mp", "ws",
))
def test_documented_id_dimension_comparison_is_case_insensitive(tmp_path, program):
    path = _constructed_program_file(tmp_path, program)
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    row = lines[1].split("\t")
    row[0] = row[0].lower()
    for field in SERIES_ID_COMPONENTS[program]:
        if field in header and field != "seasonal":
            row[header.index(field)] = row[header.index(field)].lower()
    path.write_text("\n".join([lines[0], "\t".join(row), ""]), encoding="utf-8")
    assert parse_native_series(path, program).height == 1


@pytest.mark.parametrize(
    "program",
    ("oe", "is", "wm", "ep", "nb", "tu", "or", "ln", "bd", "la", "ce", "ip",
     "le", "wd", "cu", "cm", "cw", "nd", "wp", "pc", "fm", "ci", "ei", "lu", "su", "ws"),
)
def test_seasonal_column_must_match_third_series_id_character(tmp_path, program):
    path = _constructed_program_file(tmp_path, program)
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    row = lines[1].split("\t")
    row[header.index("seasonal")] = "S" if row[0][2].upper() == "U" else "U"
    path.write_text("\n".join([lines[0], "\t".join(row), ""]), encoding="utf-8")
    with pytest.raises(NativeSeriesError, match="invalid series_id"):
        parse_native_series(path, program)


def test_saved_full_revalidation_id_examples_are_accepted_and_component_checked(tmp_path):
    records = json.loads(
        (FIXTURE_DIR / "full_revalidation_id_rows.json").read_text(encoding="utf-8")
    )
    for program, values in records["programs"].items():
        path = _constructed_program_file(tmp_path, program)
        lines = path.read_text(encoding="utf-8").splitlines()
        header = lines[0].split("\t")
        row = lines[1].split("\t")
        for field, value in values.items():
            if field in header:
                row[header.index(field)] = value
        row[0] = values["series_id"]
        path.write_text("\n".join([lines[0], "\t".join(row), ""]), encoding="utf-8")
        parsed = parse_native_series(path, program)
        assert parsed.get_column("series_id").item() == values["series_id"]
        if "seasonal" in values:
            expected = "SA" if values["seasonal"] == "S" else "NSA"
            assert parsed.get_column("seasonal").item() == expected


def test_saved_cx_short_id_record_is_accepted_and_component_checked(tmp_path):
    records = json.loads(
        (FIXTURE_DIR / "full_revalidation_id_rows.json").read_text(encoding="utf-8")
    )
    record = records["cx_short_id_record"]
    header = SOURCE_HEADERS["cx"]
    row = ["" if record[field] is None else record[field] for field in header]
    path = _write(
        tmp_path,
        ("\t".join(header) + "\n" + "\t".join(row) + "\n").encode("utf-8"),
        filename="cx-short-id.series",
    )

    parsed = parse_native_series(path, "cx")
    assert parsed.get_column("series_id").item() == "CXUBCBSLB0101M"
    assert parsed.get_column("series_title").item() == record["series_title"]
    assert parsed.get_column("seasonal").item() == "NSA"
    assert len(parsed.get_column("series_id").item()) == 14


def test_program_specific_seasonality_uses_verified_codes_and_rejects_others(tmp_path):
    assert parse_native_series(
        _constructed_program_file(tmp_path, "kv"), "kv"
    ).get_column("seasonal").item() == "NSA"
    assert parse_native_series(
        _constructed_program_file(tmp_path, "bd", seasonal="S"), "bd"
    ).get_column("seasonal").item() == "SA"
    assert parse_native_series(
        _constructed_program_file(tmp_path, "cx", seasonal="U"), "cx"
    ).get_column("seasonal").item() == "NSA"
    with pytest.raises(NativeSeriesError, match=r"invalid, blank, or missing seasonal.*'S'"):
        parse_native_series(_constructed_program_file(tmp_path, "cx", seasonal="S"), "cx")


def test_invalid_and_blank_seasonal_values_are_rejected(tmp_path):
    with pytest.raises(NativeSeriesError, match="invalid, blank, or missing seasonal.*'X'"):
        parse_native_series(_constructed_program_file(tmp_path, "ce", seasonal="X"), "ce")
    with pytest.raises(NativeSeriesError, match="invalid, blank, or missing seasonal"):
        parse_native_series(_constructed_program_file(tmp_path, "ce", seasonal=""), "ce")
    with pytest.raises(NativeSeriesError, match="invalid, blank, or missing seasonal"):
        parse_native_series(_constructed_program_file(tmp_path, "cx", seasonal=""), "cx")
