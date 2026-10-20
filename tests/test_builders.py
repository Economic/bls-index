"""Native parsing and title synthesis from local source files."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from bls_index.builders import build_program, parse_native_series, synthesize
from bls_index.schema import CANONICAL_SCHEMA, BuildError
from bls_index.scope import NATIVE_TITLE_PROGRAMS, input_files

FIXTURES = Path(__file__).parent / "fixtures"
REAL_NATIVE = FIXTURES / "real_native"
SYNTHESIZED_ROOTS = {
    "pr": FIXTURES / "two_program" / "pr",
    "sm": FIXTURES / "real_synthesized" / "sm",
    "jt": FIXTURES / "real_synthesized" / "jt",
}
HEADER = "series_id\tseasonal\tseries_title\tbegin_year\tbegin_period\tend_year\tend_period\n"


def _write(tmp_path: Path, body: str | bytes, name: str = "ap.series") -> Path:
    path = tmp_path / name
    path.write_bytes(body.encode() if isinstance(body, str) else body)
    return path


def _row(series_id="APU0000701111", seasonal="U", title="A title", begin="1980", end="2026",
         period="M08") -> str:
    return f"{series_id}\t{seasonal}\t{title}\t{begin}\tM01\t{end}\t{period}\n"


@pytest.mark.parametrize("program", NATIVE_TITLE_PROGRAMS)
def test_real_native_sample_rows_parse_to_expected(program):
    expected = json.loads((REAL_NATIVE / "expected.json").read_text(encoding="utf-8"))[program]
    frame = parse_native_series(REAL_NATIVE / f"{program}.series", program)
    assert frame.schema == CANONICAL_SCHEMA
    assert frame.to_dicts() == expected


def test_native_title_is_preserved_and_other_fields_trimmed(tmp_path):
    path = _write(tmp_path, HEADER + _row(series_id="APU0000701111   ", title="  Spaced title ",
                                          begin=" 1980", period="M08 "))
    row = parse_native_series(path, "ap").row(0, named=True)
    assert row["series_id"] == "APU0000701111"
    assert row["series_title"] == "  Spaced title "
    assert row["begin_year"] == 1980 and row["end_period"] == "M08"


def test_blank_metadata_becomes_null(tmp_path):
    row = parse_native_series(_write(tmp_path, HEADER + _row(begin="", end="", period="")), "ap")
    assert row.select("begin_year", "end_year", "end_period").row(0) == (None, None, None)


def test_extra_and_reordered_columns_are_accepted(tmp_path):
    header = "new_code\tseries_title\tseries_id\tend_period\tend_year\tbegin_year\tseasonal\n"
    path = _write(tmp_path, header + "x\tTitle\tAPU1\tM08\t2026\t1980\tS\n")
    row = parse_native_series(path, "ap").row(0, named=True)
    assert (row["series_id"], row["series_title"], row["seasonal"]) == ("APU1", "Title", "SA")


def test_missing_seasonal_column_maps_to_unknown(tmp_path):
    header = "series_id\tseries_title\tbegin_year\tend_year\tend_period\n"
    path = _write(tmp_path, header + "APU1\tTitle\t1980\t2026\tM08\n")
    assert parse_native_series(path, "ap")["seasonal"].to_list() == ["unknown"]


def test_unexpected_seasonal_code_maps_to_unknown_with_warning(tmp_path, caplog):
    path = _write(tmp_path, HEADER + _row(seasonal="X") + _row(series_id="APU2", seasonal="S"))
    with caplog.at_level(logging.WARNING):
        frame = parse_native_series(path, "ap")
    assert frame["seasonal"].to_list() == ["unknown", "SA"]
    assert "seasonal code" in caplog.text


@pytest.mark.parametrize(("body", "message"), [
    (b"", "empty"),
    (HEADER, "no data rows"),
    (HEADER.replace("series_title\t", "") + "APU1\tU\t1980\tM01\t2026\tM08\n", "missing column"),
    (HEADER.replace("seasonal", "series_id") + _row(), "duplicate column"),
    (HEADER + "APU1\tU\tTitle\t1980\tM01\t2026\n", "fields"),
    (HEADER + _row() + "\n", "fields"),
    (HEADER.encode() + _row(title="caf\xe9").encode("latin-1"), "parse"),
    (HEADER + _row(series_id=""), "blank series_id"),
    (HEADER + _row(series_id="CUU0000701111"), "does not start with"),
    (HEADER + _row() + _row(), "duplicate series_id"),
    (HEADER + _row(title="   "), "blank series_title"),
    (HEADER + _row(begin="80"), "four-digit year"),
])  # fmt: skip
def test_native_parser_rejects(tmp_path, body, message):
    with pytest.raises(BuildError, match=message):
        parse_native_series(_write(tmp_path, body), "ap")


def _synth_files(program: str, tmp_path: Path) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in input_files(program):
        files[name] = tmp_path / name
        files[name].write_bytes((SYNTHESIZED_ROOTS[program] / name).read_bytes())
    return files


def _edit(files: dict[str, Path], name: str, old: str, new: str) -> None:
    text = files[name].read_text(encoding="utf-8")
    assert old in text
    files[name].write_text(text.replace(old, new, 1), encoding="utf-8")


def test_synthesized_titles_match_approved_templates(tmp_path):
    frames = {program: synthesize(program, _synth_files(program, tmp_path / program))
              for program in SYNTHESIZED_ROOTS}
    assert {program: frame.height for program, frame in frames.items()} == {"pr": 8, "sm": 3, "jt": 4}
    assert frames["pr"]["series_title"][0] == (
        "Measure: Employment; Sector: Manufacturing; Class: All workers; "
        "Duration: % Change same quarter 1 year ago"
    )
    assert frames["sm"]["series_title"][0] == (
        "Data type: Diffusion Indexes, 1-month span, seasonally adjusted, total nonfarm; "
        "State: All States; Area: Statewide; Supersector: Total Nonfarm; Industry: Total Nonfarm"
    )
    assert frames["jt"]["series_title"][0] == (
        "Data element: Hires; Rate/level: Level - In Thousands; Industry: Total nonfarm; "
        "State: Total US; Area: All areas; Size class: All size classes"
    )
    for frame in frames.values():
        assert frame.schema == CANONICAL_SCHEMA
        assert frame["title_source"].unique().to_list() == ["synthesized"]


def test_synthesized_titles_agree_with_official_bls_reports(tmp_path):
    reports = json.loads((FIXTURES / "real_synthesized" / "sm-jt-series-descriptions.json")
                         .read_text(encoding="utf-8"))["reports"]
    for report in reports:
        program = report["program"]
        frame = synthesize(program, _synth_files(program, tmp_path / report["series_id"]))
        row = frame.filter(frame["series_id"] == report["series_id"]).row(0, named=True)
        assert row["seasonal"] == report["seasonal"]
        assert dict(part.split(": ", 1) for part in row["series_title"].split("; ")) == report["title_fields"]

    pr_reports = json.loads((FIXTURES / "real_synthesized" / "pr-series-descriptions.json")
                            .read_text(encoding="utf-8"))["reports"]
    frame = synthesize("pr", _synth_files("pr", tmp_path / "pr"))
    titles = dict(frame.select("series_id", "series_title").iter_rows())
    for report in pr_reports:
        fields = dict(part.split(": ", 1) for part in titles[report["series_id"]].split("; "))
        for field in ("Measure", "Sector", "Duration"):  # reports do not show Class
            assert fields[field] == report[field.lower()]


@pytest.mark.parametrize(("program", "name", "old", "new", "message"), [
    ("pr", "pr.sector", "3000\t", "9999\t", "not in pr.sector"),
    ("sm", "sm.state", "00\t", "99\t", "not in sm.state"),
    ("jt", "jt.sizeclass", "00\t", "99\t", "not in jt.sizeclass"),
    ("pr", "pr.measure", "Employment", " ", "blank label"),
])
def test_synthesis_rejects_missing_keys_and_labels(tmp_path, program, name, old, new, message):
    files = _synth_files(program, tmp_path)
    _edit(files, name, old, new)
    with pytest.raises(BuildError, match=message):
        synthesize(program, files)


def test_duplicate_lookup_keys_are_rejected_rather_than_multiplying_rows(tmp_path):
    files = _synth_files("sm", tmp_path)
    lines = files["sm.state"].read_text(encoding="utf-8").splitlines(keepends=True)
    files["sm.state"].write_text("".join([*lines, lines[1]]), encoding="utf-8")
    with pytest.raises(BuildError, match="duplicate lookup key"):
        synthesize("sm", files)


@pytest.mark.parametrize(("program", "old", "new"), [
    ("pr", "PRS30006011 ", "PRS31006011 "),
    ("sm", "SMS00000000000000021 ", "SMS25000000000000021 "),
    ("jt", "JTU000000000000000R1R ", "JTU000000000000000R1L "),
])
def test_series_id_must_match_the_codes_that_choose_its_title(tmp_path, program, old, new):
    files = _synth_files(program, tmp_path)
    _edit(files, f"{program}.series", old, new)
    with pytest.raises(BuildError, match="does not match its dimension codes"):
        synthesize(program, files)


def test_sm_supersector_must_match_industry_prefix(tmp_path):
    files = _synth_files("sm", tmp_path)
    _edit(files, "sm.series", "\t00\t00000000\t", "\t60\t00000000\t")
    with pytest.raises(BuildError, match="supersector_code"):
        synthesize("sm", files)


def test_pr_base_year_mismatch_warns_without_failing(tmp_path, caplog):
    files = _synth_files("pr", tmp_path)
    text = files["pr.series"].read_text(encoding="utf-8")
    index_rows = [line for line in text.splitlines() if "\t2017\t" in line]
    assert index_rows, "fixture needs an index row with base_year 2017"
    files["pr.series"].write_text(text.replace(index_rows[0], index_rows[0].replace("\t2017\t", "\t2012\t")),
                                  encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        frame = synthesize("pr", files)
    assert frame.height == 8
    assert "base_year" in caplog.text


def test_build_program_dispatches_by_program(tmp_path):
    assert build_program("ap", {"ap.series": REAL_NATIVE / "ap.series"}).height > 0
    assert build_program("pr", _synth_files("pr", tmp_path)).height == 8
    with pytest.raises(BuildError, match="no builder"):
        build_program("nw", {})
