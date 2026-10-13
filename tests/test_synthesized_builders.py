from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bls_index.http_source import DownloadRecord, InputSet
from bls_index.native_builders import CANONICAL_SCHEMA
from bls_index.synthesized_builders import (
    JT_INPUT_NAMES,
    PR_INPUT_NAMES,
    SM_INPUT_NAMES,
    SynthesizedSeriesError,
    parse_jt_input_set,
    parse_jt_sources,
    parse_pr_input_set,
    parse_pr_sources,
    parse_sm_input_set,
    parse_sm_sources,
)

FIXTURES = Path(__file__).parent / "fixtures" / "two_program" / "pr"
REPORT_FIXTURE = Path(__file__).parent / "fixtures" / "real_synthesized" / "pr-series-descriptions.json"


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


def test_pr_builder_title_fields_match_independent_bls_reports(tmp_path):
    frame = parse_pr_sources(_sources(tmp_path))
    report_records = json.loads(REPORT_FIXTURE.read_text(encoding="utf-8"))["reports"]
    reports = {report["series_id"]: report for report in report_records}
    series_ids = ("PRS30006011", "PRS30006012", "PRS30006013")
    generated_titles = dict(
        zip(
            frame.get_column("series_id").to_list(),
            frame.get_column("series_title").to_list(),
            strict=True,
        )
    )

    for series_id in series_ids:
        report = reports[series_id]
        title_components = dict(
            component.split(": ", maxsplit=1)
            for component in generated_titles[series_id].split("; ")
        )
        for component in ("Measure", "Sector", "Duration"):
            assert title_components[component] == report[component.lower()]
        # Official series reports do not expose Class, so this test does not
        # independently verify the generated "All workers" component.


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


REAL_FIXTURES = Path(__file__).parent / "fixtures" / "real_synthesized"
SM_JT_REPORTS = REAL_FIXTURES / "sm-jt-series-descriptions.json"


def _program_sources(tmp_path: Path, program: str, names: tuple[str, ...]) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixture_dir = REAL_FIXTURES / program
    result = {}
    for name in names:
        path = tmp_path / name
        path.write_bytes((fixture_dir / name).read_bytes())
        result[name] = path
    return result


def _verified_program_input_set(program: str, sources: dict[str, Path], names: tuple[str, ...]) -> InputSet:
    records = []
    rechecks = []
    now = datetime.now(UTC)
    for name in names:
        body = sources[name].read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        url = f"https://download.bls.gov/pub/time.series/{program}/{name}"
        records.append(DownloadRecord(url, sources[name], 200, len(body), digest, {}, now, now, 1))
        rechecks.append(DownloadRecord(url, None, 200, len(body), digest, {}, now, now, 1))
    return InputSet(program, tuple(records), tuple(rechecks), 1)


def test_sm_jt_real_fixture_templates_and_report_fields(tmp_path):
    reports = json.loads(SM_JT_REPORTS.read_text(encoding="utf-8"))["reports"]
    for program, names, parser, report_id in (
        ("sm", SM_INPUT_NAMES, parse_sm_sources, "SMS00000000000000021"),
        ("jt", JT_INPUT_NAMES, parse_jt_sources, "JTS000000000000000HIR"),
    ):
        frame = parser(_program_sources(tmp_path / program, program, names))
        assert frame.schema == CANONICAL_SCHEMA
        assert frame.height == (3 if program == "sm" else 4)
        assert frame.get_column("title_source").unique().to_list() == ["synthesized"]
        report = next(item for item in reports if item["series_id"] == report_id)
        index = frame.get_column("series_id").to_list().index(report_id)
        assert frame.get_column("seasonal").item(index) == report["seasonal"]
        components = dict(
            part.split(": ", maxsplit=1)
            for part in frame.get_column("series_title").item(index).split("; ")
        )
        assert components == report["title_fields"]

    sm_sources = _program_sources(tmp_path / "sm-exact", "sm", SM_INPUT_NAMES)
    sm_frame = parse_sm_sources(sm_sources)
    assert sm_frame.get_column("series_title").item(0) == (
        "Data type: Diffusion Indexes, 1-month span, seasonally adjusted, total nonfarm; "
        "State: All States; Area: Statewide; Supersector: Total Nonfarm; Industry: Total Nonfarm"
    )
    jt_sources = _program_sources(tmp_path / "jt-exact", "jt", JT_INPUT_NAMES)
    jt_frame = parse_jt_sources(jt_sources)
    assert jt_frame.get_column("series_title").item(0) == (
        "Data element: Hires; Rate/level: Level - In Thousands; Industry: Total nonfarm; "
        "State: Total US; Area: All areas; Size class: All size classes"
    )


@pytest.mark.parametrize(("program", "names", "parser"), [
    ("sm", SM_INPUT_NAMES, parse_sm_sources), ("jt", JT_INPUT_NAMES, parse_jt_sources),
])
def test_sm_jt_verified_input_set_rechecks_and_cardinality(tmp_path, program, names, parser):
    sources = _program_sources(tmp_path, program, names)
    verified = _verified_program_input_set(program, sources, names)
    input_parser = parse_sm_input_set if program == "sm" else parse_jt_input_set
    frame = input_parser(verified)
    assert frame.schema == CANONICAL_SCHEMA
    assert frame.height == len(sources[f"{program}.series"].read_text(encoding="utf-8").splitlines()) - 1

    changed = list(verified.rechecks)
    item = changed[0]
    changed[0] = DownloadRecord(item.url, None, item.status, item.bytes, "0" * 64, {}, item.started_at, item.finished_at, 1)
    with pytest.raises(SynthesizedSeriesError, match="does not match input record"):
        input_parser(InputSet(program, verified.files, tuple(changed), verified.attempts))


@pytest.mark.parametrize(("program", "names", "parser", "dimension", "old", "new", "error"), [
    ("sm", SM_INPUT_NAMES, parse_sm_sources, "state", "state_code", "STATE", "unexpected header"),
    ("jt", JT_INPUT_NAMES, parse_jt_sources, "industry", "industry_code", "INDUSTRY", "unexpected header"),
])
def test_sm_jt_exact_headers_and_lookup_required(tmp_path, program, names, parser, dimension, old, new, error):
    sources = _program_sources(tmp_path, program, names)
    _replace(sources, f"{program}.{dimension}", old, new)
    with pytest.raises(SynthesizedSeriesError, match=error):
        parser(sources)


@pytest.mark.parametrize(("program", "names", "parser", "name", "old", "new", "error"), [
    ("sm", SM_INPUT_NAMES, parse_sm_sources, "sm.state", "00\tAll States", "00\t ", "blank lookup label"),
    ("jt", JT_INPUT_NAMES, parse_jt_sources, "jt.industry", "000000\tTotal nonfarm", "000000\t ", "blank lookup label"),
    ("sm", SM_INPUT_NAMES, parse_sm_sources, "sm.industry", "00000000\tTotal Nonfarm", "00000000\tTotal Nonfarm\n00000000\tDuplicate", "duplicate trimmed lookup key"),
    ("jt", JT_INPUT_NAMES, parse_jt_sources, "jt.ratelevel", "L\tLevel - In Thousands", "X\tLevel - In Thousands", "missing ratelevel lookup key"),
])
def test_sm_jt_duplicate_blank_and_missing_lookup_errors(tmp_path, program, names, parser, name, old, new, error):
    sources = _program_sources(tmp_path, program, names)
    _replace(sources, name, old, new)
    with pytest.raises(SynthesizedSeriesError, match=error):
        parser(sources)


@pytest.mark.parametrize(("program", "names", "parser", "column", "new", "error"), [
    ("sm", SM_INPUT_NAMES, parse_sm_sources, "state_code", "25", "does not match source components"),
    ("sm", SM_INPUT_NAMES, parse_sm_sources, "supersector_code", "06", "supersector_code does not match"),
    ("sm", SM_INPUT_NAMES, parse_sm_sources, "data_type_code", "99", "missing data_type lookup key"),
    ("jt", JT_INPUT_NAMES, parse_jt_sources, "ratelevel_code", "X", "missing ratelevel lookup key"),
    ("jt", JT_INPUT_NAMES, parse_jt_sources, "sizeclass_code", "99", "missing sizeclass lookup key"),
])
def test_sm_jt_source_id_dimension_and_supersector_validation(tmp_path, program, names, parser, column, new, error):
    sources = _program_sources(tmp_path, program, names)
    lines = sources[f"{program}.series"].read_text(encoding="utf-8").splitlines()
    header = [field.strip() for field in lines[0].split("\t")]
    row = lines[1].split("\t")
    row[header.index(column)] = new
    lines[1] = "\t".join(row)
    sources[f"{program}.series"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(SynthesizedSeriesError, match=error):
        parser(sources)


@pytest.mark.parametrize(("program", "names", "parser", "old", "new", "error"), [
    ("sm", SM_INPUT_NAMES, parse_sm_sources, "\tS\t2025\t", "\tX\t2025\t", "invalid, blank, or missing seasonal"),
    ("jt", JT_INPUT_NAMES, parse_jt_sources, "\tS\t000000\t", "\tX\t000000\t", "invalid, blank, or missing seasonal"),
    ("sm", SM_INPUT_NAMES, parse_sm_sources, "\t1991\tM01\t2026\tM08", "\t0000\tM01\t2026\tM08", "invalid begin_year"),
    ("jt", JT_INPUT_NAMES, parse_jt_sources, "\t2000\tM12\t2026\tM08", "\t2000\tM99\t2026\tM08", "invalid period code"),
])
def test_sm_jt_seasonal_and_date_validation(tmp_path, program, names, parser, old, new, error):
    sources = _program_sources(tmp_path, program, names)
    _replace(sources, f"{program}.series", old, new)
    with pytest.raises(SynthesizedSeriesError, match=error):
        parser(sources)
