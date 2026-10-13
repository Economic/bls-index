from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bls_index.http_source import DownloadRecord, InputSet
from bls_index.native_builders import CANONICAL_SCHEMA
from bls_index.synthesized_builders import (
    PR_INPUT_NAMES,
    SynthesizedSeriesError,
    parse_pr_input_set,
    parse_pr_sources,
)

FIXTURES = Path(__file__).parent / "fixtures" / "two_program" / "pr"


def _sources(tmp_path: Path) -> dict[str, Path]:
    result = {}
    for name in PR_INPUT_NAMES:
        path = tmp_path / name
        path.write_bytes((FIXTURES / name).read_bytes())
        result[name] = path
    return result


def _text(sources: dict[str, Path], name: str) -> str:
    return sources[name].read_text(encoding="utf-8")


def _replace(sources: dict[str, Path], name: str, old: str, new: str) -> None:
    path = sources[name]
    path.write_text(_text(sources, name).replace(old, new, 1), encoding="utf-8")


def _verified_input_set(sources: dict[str, Path]) -> InputSet:
    records = []
    rechecks = []
    now = datetime.now(UTC)
    for name in PR_INPUT_NAMES:
        body = sources[name].read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        url = f"https://download.bls.gov/pub/time.series/pr/{name}"
        records.append(DownloadRecord(url, sources[name], 200, len(body), digest, {}, now, now, 1))
        rechecks.append(DownloadRecord(url, None, 200, len(body), digest, {}, now, now, 1))
    return InputSet("pr", tuple(records), tuple(rechecks), 1)


def test_pr_builder_returns_exact_canonical_schema_and_approved_title(tmp_path):
    frame = parse_pr_sources(_sources(tmp_path))
    assert frame.schema == CANONICAL_SCHEMA
    assert frame.height == 8
    assert frame.get_column("series_title").item(0) == (
        "Measure: Employment; Sector: Manufacturing; Class: All workers; "
        "Duration: % Change same quarter 1 year ago"
    )
    assert frame.get_column("title_source").unique().to_list() == ["synthesized"]
    assert frame.get_column("program").unique().to_list() == ["pr"]


def test_pr_builder_uses_seasonal_lookup_and_preserves_trimmed_ids(tmp_path):
    sources = _sources(tmp_path)
    frame = parse_pr_sources(sources)
    assert frame.get_column("series_id").to_list() == [
        "PRS30006011", "PRS30006012", "PRS30006013", "PRS30006021",
        "PRS30006022", "PRS30006023", "PRS30006031", "PRS30006032",
    ]
    assert frame.get_column("seasonal").to_list() == ["SA"] * 8

    _replace(sources, "pr.series", "PRS30006011", "prs30006011")
    lower_id_frame = parse_pr_sources(sources)
    assert lower_id_frame.get_column("series_id").item(0) == "prs30006011"

    series_path = sources["pr.series"]
    series_path.write_text(
        _text(sources, "pr.series")
        + "PRU30006011\t3000\t6\t01\t1\tU\t-\t\t1988\tQ01\t2026\tQ02\n",
        encoding="utf-8",
    )
    with_u = parse_pr_sources(sources)
    assert with_u.height == frame.height + 1
    assert with_u.get_column("series_id").item(-1) == "PRU30006011"
    assert with_u.get_column("seasonal").item(-1) == "NSA"

    _replace(sources, "pr.seasonal", "S\tSeasonal Adjusted", "S\tSeasonally Adjusted")
    with pytest.raises(SynthesizedSeriesError, match="seasonal lookup labels"):
        parse_pr_sources(sources)


def test_verified_input_set_api_parses_fixture_without_downloading(tmp_path):
    sources = _sources(tmp_path)
    frame = parse_pr_input_set(_verified_input_set(sources))
    assert frame.schema == CANONICAL_SCHEMA
    assert frame.height == 8


@pytest.mark.parametrize(
    ("name", "body", "message"),
    [
        ("pr.series", lambda b: b.replace(b"\t", b" ", 1), "unexpected header"),
        ("pr.series", lambda b: b.replace(b"PRS30006011", b"PRS30006011\textra", 1), "expected 12"),
        ("pr.measure", lambda b: b.replace(b"Employment", b"Employ\xffment", 1), "not valid UTF-8"),
        ("pr.sector", lambda b: b.replace(b"\t", b" ", 1), "unexpected header"),
    ],
)
def test_malformed_tabs_headers_width_and_utf8_rejected(tmp_path, name, body, message):
    sources = _sources(tmp_path)
    sources[name].write_bytes(body(sources[name].read_bytes()))
    with pytest.raises(SynthesizedSeriesError, match=message):
        parse_pr_sources(sources)


def test_duplicate_trimmed_lookup_keys_rejected_even_with_same_label(tmp_path):
    sources = _sources(tmp_path)
    _replace(
        sources,
        "pr.sector",
        "3000\tManufacturing\t0\tT\t4",
        "3000\tManufacturing\t0\tT\t4\n 3000 \tManufacturing\t0\tT\t4",
    )
    with pytest.raises(SynthesizedSeriesError, match="duplicate trimmed lookup key '3000'"):
        parse_pr_sources(sources)


@pytest.mark.parametrize(
    ("name", "old", "new", "message"),
    [
        ("pr.sector", "3000\tManufacturing", "9999\tManufacturing", "missing sector lookup key"),
        ("pr.measure", "01\tEmployment", "01\t   ", "blank lookup label"),
        ("pr.duration", "1\t% Change same quarter 1 year ago", "1\t ", "blank lookup label"),
    ],
)
def test_missing_joins_and_blank_lookup_labels_rejected(tmp_path, name, old, new, message):
    sources = _sources(tmp_path)
    _replace(sources, name, old, new)
    with pytest.raises(SynthesizedSeriesError, match=message):
        parse_pr_sources(sources)


def test_duplicate_trimmed_series_ids_rejected(tmp_path):
    sources = _sources(tmp_path)
    _replace(sources, "pr.series", "PRS30006012", "  PRS30006011 ")
    with pytest.raises(SynthesizedSeriesError, match="duplicate trimmed series_id 'PRS30006011'"):
        parse_pr_sources(sources)


@pytest.mark.parametrize("bad_id", ["PR", "PRX30006011", "PRS3000601", "PRS3000601_", "QRS30006011", "PRS3000601-1"])
def test_malformed_pr_ids_rejected(tmp_path, bad_id):
    sources = _sources(tmp_path)
    _replace(sources, "pr.series", "PRS30006011", bad_id)
    with pytest.raises(SynthesizedSeriesError, match="invalid PR series_id"):
        parse_pr_sources(sources)


@pytest.mark.parametrize(
    ("field", "old", "new"),
    [
        ("sector_code", "3000", "3100"),
        ("class_code", "6", "3"),
        ("measure_code", "01", "02"),
        ("duration_code", "1", "2"),
    ],
)
def test_each_pr_id_source_component_must_match(field, old, new, tmp_path):
    sources = _sources(tmp_path)
    lines = sources["pr.series"].read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    row = lines[1].split("\t")
    row[header.index(field)] = new
    lines[1] = "\t".join(row)
    sources["pr.series"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(SynthesizedSeriesError, match="does not match source components"):
        parse_pr_sources(sources)


def test_index_duration_base_year_match_conflict_and_non_index_base(tmp_path):
    sources = _sources(tmp_path)
    # The fixture's index row is duration 3 and correctly says base_year 2017.
    assert parse_pr_sources(sources).height == 8

    # Making duration 1 explicitly an index still permits an absent base-year row only
    # when it agrees; the first fixture row has '-'.
    _replace(sources, "pr.duration", "1\t% Change same quarter 1 year ago", "1\tIndex (2017=100)")
    with pytest.raises(SynthesizedSeriesError, match="base_year '-' does not match index duration base '2017'"):
        parse_pr_sources(sources)

    # A matching index base is accepted and the approved template is unchanged.
    series_path = sources["pr.series"]
    series_path.write_text(
        series_path.read_text(encoding="utf-8").replace("\t1\tS\t-\t", "\t1\tS\t2017\t"),
        encoding="utf-8",
    )
    matched = parse_pr_sources(sources)
    assert matched.get_column("series_title").item(0) == (
        "Measure: Employment; Sector: Manufacturing; Class: All workers; Duration: Index (2017=100)"
    )

    lines = sources["pr.series"].read_text(encoding="utf-8").splitlines()
    index_row = lines[3].split("\t")
    index_row[6] = "2018"
    lines[3] = "\t".join(index_row)
    sources["pr.series"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(SynthesizedSeriesError, match="base_year '2018' does not match index duration base '2017'"):
        parse_pr_sources(sources)

    # An explicit base on a non-index duration label is not reinterpreted as an index rule.
    index_row[6] = "2017"
    lines[3] = "\t".join(index_row)
    sources["pr.series"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    _replace(sources, "pr.duration", "1\tIndex (2017=100)", "1\tPercent change")
    assert parse_pr_sources(sources).height == 8


@pytest.mark.parametrize(
    ("name", "old", "new", "message"),
    [
        ("pr.series", "\t1988\tQ01\t2026\tQ02", "\t1988\tQ99\t2026\tQ02", "invalid period code"),
        ("pr.series", "\t1988\tQ01\t2026\tQ02", "\t2027\tQ01\t2026\tQ02", "begin_year exceeds end_year"),
        ("pr.series", "\tS\t-\t\t1988", "\tX\t-\t\t1988", "invalid, blank, or missing seasonal"),
        ("pr.series", "\tS\t-\t\t1988", "\t\t-\t\t1988", "blank required seasonal key"),
    ],
)
def test_invalid_dates_periods_and_seasonal_values_rejected(tmp_path, name, old, new, message):
    sources = _sources(tmp_path)
    _replace(sources, name, old, new)
    with pytest.raises(SynthesizedSeriesError, match=message):
        parse_pr_sources(sources)


def test_lookup_join_does_not_multiply_rows_and_each_source_row_has_output(tmp_path):
    sources = _sources(tmp_path)
    frame = parse_pr_sources(sources)
    source_data_count = len(sources["pr.series"].read_text(encoding="utf-8").splitlines()) - 1
    assert frame.height == source_data_count == 8
    assert frame.get_column("series_id").n_unique() == source_data_count


def test_invalid_verified_input_set_rejected_before_parse(tmp_path):
    sources = _sources(tmp_path)
    valid = _verified_input_set(sources)
    with pytest.raises(SynthesizedSeriesError, match="does not match input record"):
        bad = list(valid.rechecks)
        bad[0] = DownloadRecord(
            bad[0].url, None, 200, bad[0].bytes, "0" * 64, {}, bad[0].started_at,
            bad[0].finished_at, 1,
        )
        parse_pr_input_set(InputSet("pr", valid.files, tuple(bad), 1))
