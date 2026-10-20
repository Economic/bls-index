"""Combined candidate checks and the pinned data-dict validation."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import polars as pl
import pytest

from bls_index.builders import build_program
from bls_index.combined_candidate import (
    DICTIONARY,
    CombinedCandidateError,
    validate_combined_candidate,
    write_combined_candidate,
)
from bls_index.schema import CANONICAL_SCHEMA
from bls_index.scope import INITIAL_PROGRAMS, NATIVE_TITLE_PROGRAMS, input_files

FIXTURES = Path(__file__).parent / "fixtures"


def _frame(program="ap", series_id="APU0000701111", *, title="A title", begin_year=1980,
           end_year=2026, end_period="M08", **overrides) -> pl.DataFrame:
    row = {
        "program": program, "series_id": series_id, "series_title": title,
        "title_source": "synthesized" if program in {"sm", "jt", "pr"} else "native",
        "seasonal": "unknown", "begin_year": begin_year, "end_year": end_year,
        "end_period": end_period, **overrides,
    }  # fmt: skip
    return pl.DataFrame([row]).cast(CANONICAL_SCHEMA)


def _fixture_frames() -> dict[str, pl.DataFrame]:
    roots = {program: FIXTURES / "real_native" for program in NATIVE_TITLE_PROGRAMS}
    roots |= {"pr": FIXTURES / "two_program" / "pr", "sm": FIXTURES / "real_synthesized" / "sm",
              "jt": FIXTURES / "real_synthesized" / "jt"}
    return {program: build_program(program, {name: roots[program] / name
                                             for name in input_files(program)})
            for program in INITIAL_PROGRAMS}


def test_root_dictionary_passes_spec_check():
    result = subprocess.run([shutil.which("data-dict"), "validate-spec", str(DICTIONARY), "--json"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_duplicate_titles_are_accepted_but_id_collisions_are_not():
    same_title = _frame(title="Same").vstack(_frame(series_id="APU0000701112", title="Same"))
    assert validate_combined_candidate({"ap": same_title}, ["ap"]).height == 2

    collision = {"ap": _frame(series_id="X1"), "ce": _frame("ce", series_id="X1")}
    with pytest.raises(CombinedCandidateError, match="appears in programs"):
        validate_combined_candidate(collision, ["ap", "ce"])


@pytest.mark.parametrize(("frames", "requested", "message"), [
    ({}, [], "nonempty"),
    ({"ap": _frame()}, ["ap", "ap"], "unique"),
    ({"nw": _frame("nw")}, ["nw"], "outside scope"),
    ({"ap": _frame()}, ["ap", "ce"], "do not match"),
    ({"ap": _frame().clear()}, ["ap"], "no rows"),
    ({"ap": _frame(title_source="synthesized")}, ["ap"], "title_source"),
    ({"ap": _frame("ce")}, ["ap"], "program"),
    ({"ap": _frame().with_columns(pl.col("begin_year").cast(pl.Int64))}, ["ap"], "schema"),
])  # fmt: skip
def test_candidate_rejects(frames, requested, message):
    with pytest.raises(CombinedCandidateError, match=message):
        validate_combined_candidate(frames, requested)


def test_all_initial_program_fixtures_build_and_validate(tmp_path):
    frames = _fixture_frames()
    combined = write_combined_candidate(frames, INITIAL_PROGRAMS, tmp_path)
    written = pl.read_parquet(tmp_path / "bls_index.parquet")
    assert written.equals(combined)
    assert set(written["program"]) == set(INITIAL_PROGRAMS)


@pytest.mark.parametrize(("change", "message"), [
    ({"begin_year": 99}, "begin_year"),
    ({"end_year": 10000}, "end_year"),
    ({"begin_year": 2026, "end_year": 1980}, "begin_year"),
    ({"series_id": " APU1 "}, "series_id"),
    ({"series_title": " "}, "series_title"),
    ({"seasonal": "S"}, "seasonal"),
])
def test_data_dict_rejects_bad_rows_and_leaves_no_candidate(tmp_path, change, message):
    frame = _frame().with_columns(**{name: pl.lit(value).cast(CANONICAL_SCHEMA[name])
                                     for name, value in change.items()})
    with pytest.raises(CombinedCandidateError, match="validate-data") as info:
        write_combined_candidate({"ap": frame}, ["ap"], tmp_path)
    assert message in str(info.value)
    assert not (tmp_path / "bls_index.parquet").exists()


def test_null_years_and_period_pass_validation(tmp_path):
    frame = _frame(begin_year=None, end_year=None, end_period=None)
    write_combined_candidate({"ap": frame}, ["ap"], tmp_path)
    assert pl.read_parquet(tmp_path / "bls_index.parquet").row(0, named=True)["begin_year"] is None


def test_writer_works_from_another_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_combined_candidate({"ap": _frame()}, ["ap"], Path("out"))
    assert (tmp_path / "out" / "bls_index.parquet").is_file()
