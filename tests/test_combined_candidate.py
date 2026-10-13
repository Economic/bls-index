from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import polars as pl
import pytest

from bls_index.combined_candidate import (
    CombinedCandidateError,
    validate_combined_candidate,
    write_combined_candidate,
)
from bls_index.native_builders import CANONICAL_SCHEMA, parse_native_series
from bls_index.scope import INITIAL_PROGRAMS, NATIVE_TITLE_PROGRAMS
from bls_index.synthesized_builders import (
    JT_INPUT_NAMES,
    PR_INPUT_NAMES,
    SM_INPUT_NAMES,
    parse_jt_sources,
    parse_pr_sources,
    parse_sm_sources,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
DICTIONARY = ROOT / "data-dict.yaml"


def _frame(
    program: str = "ap",
    series_id: str = "APU0000701111",
    *,
    title: str = "A title",
    title_source: str | None = None,
    seasonal: str = "unknown",
    begin_year: int | None = 1980,
    end_year: int | None = 2026,
    end_period: str | None = "M08",
) -> pl.DataFrame:
    if title_source is None:
        title_source = "synthesized" if program in {"sm", "jt", "pr"} else "native"
    return pl.DataFrame(
        {
            "program": [program],
            "series_id": [series_id],
            "series_title": [title],
            "title_source": [title_source],
            "seasonal": [seasonal],
            "begin_year": pl.Series([begin_year], dtype=pl.Int32),
            "end_year": pl.Series([end_year], dtype=pl.Int32),
            "end_period": [end_period],
        }
    ).cast(CANONICAL_SCHEMA)


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    exe = shutil.which("data-dict")
    assert exe, "data-dict must be run in the locked uv environment"
    return subprocess.run([exe, *args], cwd=ROOT, capture_output=True, text=True)


def _real_fixture_frames() -> dict[str, pl.DataFrame]:
    frames = {
        program: parse_native_series(
            FIXTURES / "real_native" / f"{program}.series", program
        )
        for program in NATIVE_TITLE_PROGRAMS
    }
    for program, names, parser in (
        ("sm", SM_INPUT_NAMES, parse_sm_sources),
        ("jt", JT_INPUT_NAMES, parse_jt_sources),
    ):
        root = FIXTURES / "real_synthesized" / program
        frames[program] = parser({name: root / name for name in names})
    pr_root = FIXTURES / "two_program" / "pr"
    frames["pr"] = parse_pr_sources(
        {name: pr_root / name for name in PR_INPUT_NAMES}
    )
    return frames


def test_root_dictionary_passes_pinned_cli_spec_check():
    result = _cli("validate-spec", str(DICTIONARY), "--json")
    assert result.returncode == 0, result.stdout + result.stderr


def test_combined_candidate_accepts_duplicate_titles_but_rejects_id_collision():
    accepted = validate_combined_candidate(
        {
            "ap": _frame(title="same title"),
            "jt": _frame("jt", "JTS000000000000000HIR", title="same title", seasonal="SA"),
        },
        ["ap", "jt"],
    )
    assert accepted.height == 2
    assert accepted.get_column("series_title").to_list() == ["same title", "same title"]

    duplicated = _frame().vstack(_frame(series_id="APU0000701111", title="another row"))
    with pytest.raises(CombinedCandidateError, match="series_id collision across combined candidate"):
        validate_combined_candidate({"ap": duplicated}, ["ap"])

    for malformed in ("AP-", "APU00007011111", "CES0000000001"):
        with pytest.raises(CombinedCandidateError, match="invalid BLS series_id"):
            validate_combined_candidate({"ap": _frame(series_id=malformed)}, ["ap"])
    with pytest.raises(CombinedCandidateError, match="invalid BLS series_id"):
        validate_combined_candidate({"ce": _frame("ce", "CES_____", seasonal="NSA")}, ["ce"])

    null_id = _frame().with_columns(pl.lit(None, dtype=pl.String).alias("series_id"))
    with pytest.raises(CombinedCandidateError, match="missing, untrimmed, or invalid BLS series_id"):
        validate_combined_candidate({"ap": null_id}, ["ap"])


@pytest.mark.parametrize(
    ("program", "series_id"),
    [
        ("sm", "SM"),
        ("sm", "SMU0000000000000002A"),
        ("jt", "JT000000000000000HIR"),
        ("jt", "JTS00000000000000_HIR"),
        ("jt", "JTS000000000000000HIK"),
        ("pr", "PRX30006011"),
        ("pr", "PRS3000601"),
    ],
)
def test_synthesized_ids_require_exact_shape(program: str, series_id: str):
    with pytest.raises(CombinedCandidateError, match="invalid BLS series_id"):
        validate_combined_candidate({program: _frame(program, series_id)}, [program])


@pytest.mark.parametrize(
    ("program", "series_id", "seasonal"),
    [
        ("sm", "SMU00000000000000021", "SA"),
        ("sm", "SMS00000000000000021", "NSA"),
        ("jt", "JTU000000000000000HIR", "SA"),
        ("jt", "JTS000000000000000HIR", "NSA"),
        ("pr", "PRU30006011", "SA"),
        ("pr", "PRS30006011", "NSA"),
    ],
)
def test_known_seasonal_value_must_match_id_code(
    program: str, series_id: str, seasonal: str
):

    with pytest.raises(CombinedCandidateError, match="seasonal code inconsistent"):
        validate_combined_candidate(
            {program: _frame(program, series_id, seasonal=seasonal)}, [program]
        )


def test_unknown_seasonal_is_limited_to_programs_without_verified_seasonal_values():
    frame = _frame("ap", "APU0000701111", seasonal="unknown")
    assert validate_combined_candidate({"ap": frame}, ["ap"]).height == 1


@pytest.mark.parametrize(
    ("program", "series_id", "seasonal"),
    [
        ("ap", "APU0000701111", "SA"),
        ("ap", "APU0000701111", "NSA"),
        ("mp", "MPU000000", "NSA"),
        ("kv", "KVU0100000000000001", "SA"),
        ("cx", "CXU001000LB0101M", "SA"),
        ("ce", "CES0000000001", "unknown"),
    ],
)
def test_seasonal_values_must_be_available_for_program(
    program: str, series_id: str, seasonal: str
):
    with pytest.raises(CombinedCandidateError, match="seasonal value outside"):
        validate_combined_candidate(
            {program: _frame(program, series_id, seasonal=seasonal)}, [program]
        )


def test_u_only_programs_and_synthesized_programs_accept_nsa():
    for program, series_id in (
        ("kv", "KVU0100000000000001"),
        ("cx", "CXU001000LB0101M"),
        ("sm", "SMU00000000000000021"),
        ("jt", "JTU000000000000000HIR"),
        ("pr", "PRU30006011"),
    ):
        assert validate_combined_candidate(
            {program: _frame(program, series_id, seasonal="NSA")}, [program]
        ).height == 1


def test_combined_candidate_accepts_requested_native_subset():
    frames = {
        "ap": _frame("ap", "APU0000701111"),
        "cu": _frame("cu", "CUUS0000SAF111", seasonal="NSA", end_period="S03"),
    }
    combined = validate_combined_candidate(frames, ["ap", "cu"])
    assert combined.height == 2
    assert set(combined.get_column("program")) == {"ap", "cu"}


def test_combined_scope_and_title_source_are_checked():
    with pytest.raises(CombinedCandidateError, match="outside initial scope"):
        validate_combined_candidate({"xx": _frame("xx")}, ["xx"])
    with pytest.raises(CombinedCandidateError, match="scope mismatch"):
        validate_combined_candidate(
            {"ap": _frame(), "jt": _frame("jt", "JTS000000000000000HIR")}, ["ap"]
        )
    with pytest.raises(CombinedCandidateError, match="requested program scope contains duplicates"):
        validate_combined_candidate({"ap": _frame()}, ["ap", "ap"])
    with pytest.raises(CombinedCandidateError, match="requires title_source 'synthesized'"):
        validate_combined_candidate(
            {"jt": _frame("jt", "JTS000000000000000HIR", title_source="native")}, ["jt"]
        )


def test_combined_bls_specific_checks_preserve_native_title_content():
    frame = _frame(series_id="APU0000701111", title="  Native title with spaces  ")
    assert validate_combined_candidate({"ap": frame}, ["ap"]).item(0, "series_title") == "  Native title with spaces  "

    cases = [
        (_frame(series_id=" "), "series_id"),
        (_frame(series_id=" APU1"), "series_id"),
        (_frame(title=" \t "), "whitespace-only series_title"),
        (_frame(seasonal="S"), "seasonal value"),
        (_frame(begin_year=999), "four-digit year range"),
        (_frame(begin_year=10000), "four-digit year range"),
        (_frame(begin_year=2027), "begin_year later than end_year"),
        (_frame(end_period="M00"), "unsupported BLS end_period"),
        (_frame(end_period="S01"), "unsupported BLS end_period"),
        (_frame(end_year=None, end_period="M01"), "end_period without end_year"),
    ]
    for invalid, expected_message in cases:
        with pytest.raises(CombinedCandidateError, match=expected_message):
            validate_combined_candidate({"ap": invalid}, ["ap"])


def test_semiannual_periods_are_scoped_to_cu_and_cw(tmp_path):
    cu = _frame("cu", "CUUS0000SAF111", seasonal="NSA", end_period="S03")
    cw = _frame("cw", "CWSR0000SA0", seasonal="SA", end_period="S03")
    assert validate_combined_candidate({"cu": cu}, ["cu"]).item(0, "end_period") == "S03"
    assert validate_combined_candidate({"cw": cw}, ["cw"]).item(0, "end_period") == "S03"

    for program, series_id in (("cu", "CUUS0000SAF111"), ("cw", "CWSR0000SA0")):
        seasonal = "NSA" if series_id.startswith("CU") else "SA"
        for period in ("S04", "Q01", "A01"):
            with pytest.raises(CombinedCandidateError, match="unsupported BLS end_period"):
                validate_combined_candidate(
                    {
                        program: _frame(
                            program, series_id, seasonal=seasonal, end_period=period
                        )
                    },
                    [program],
                )
    with pytest.raises(CombinedCandidateError, match="unsupported BLS end_period"):
        validate_combined_candidate({"ap": _frame(end_period="S03")}, ["ap"])
    with pytest.raises(CombinedCandidateError, match="unsupported BLS end_period"):
        validate_combined_candidate(
            {"su": _frame("su", "SUUR0000SA0", seasonal="NSA", end_period="S03")},
            ["su"],
        )

    output = tmp_path / "cu" / "bls_index.parquet"
    write_combined_candidate({"cu": cu}, ["cu"], output, dictionary_path=DICTIONARY)
    assert pl.read_parquet(output).get_column("end_period").item() == "S03"


def test_combined_rejects_incorrect_polars_types():
    wrong = _frame().with_columns(pl.col("begin_year").cast(pl.Float64))
    with pytest.raises(CombinedCandidateError, match="expected canonical schema"):
        validate_combined_candidate({"ap": wrong}, ["ap"])


def test_data_dict_cli_validates_candidate_and_rejects_data_constraints(tmp_path):
    output = tmp_path / "candidate" / "bls_index.parquet"
    frame = _frame(title="same").vstack(
        _frame(
            series_id="APU0000701112",
            title="same",
            begin_year=None,
            end_year=None,
            end_period=None,
        )
    )
    write_combined_candidate({"ap": frame}, ["ap"], output, dictionary_path=DICTIONARY)
    assert output.is_file()
    assert pl.read_parquet(output).schema == CANONICAL_SCHEMA

    bad_cases = [
        (frame.with_columns(pl.lit(None, dtype=pl.String).alias("series_id")), "required"),
        (frame.with_columns(pl.lit(None, dtype=pl.String).alias("series_title")), "required"),
        (frame.with_columns(pl.lit(" \t ").alias("series_title")), "series_title"),
        (frame.with_columns(pl.lit("S").alias("seasonal")), "values"),
        (frame.with_columns(pl.lit("duplicate").alias("series_id")), "unique"),
        (frame.with_columns(pl.lit(" padded ").alias("series_id")), "series_id"),
        (frame.with_columns(pl.lit("xx").alias("program")), "program"),
        (frame.with_columns(pl.lit("synthesized").alias("title_source")), "title_source"),
        (frame.with_columns(pl.col("begin_year").cast(pl.String)), "type"),
    ]
    for index, (bad_frame, message) in enumerate(bad_cases):
        candidate_dir = tmp_path / f"bad-{index}"
        candidate_dir.mkdir()
        parquet = candidate_dir / "bls_index.parquet"
        bad_frame.write_parquet(parquet)
        dictionary = candidate_dir / "data-dict.yaml"
        dictionary.write_text(DICTIONARY.read_text(encoding="utf-8"), encoding="utf-8")
        result = _cli("validate-data" if message != "type" else "validate-meta", str(dictionary), "--json")
        assert result.returncode != 0, result.stdout + result.stderr
        assert message.lower() in (result.stdout + result.stderr).lower()


def test_all_initial_program_fixtures_build_and_validate_staged_candidate(tmp_path):
    frames = _real_fixture_frames()
    assert set(frames) == set(INITIAL_PROGRAMS)
    assert sum(frame.height for frame in frames.values()) > 33
    titles = {
        (program, series_id): title
        for program, frame in frames.items()
        for series_id, title in frame.select("series_id", "series_title").iter_rows()
    }

    output = tmp_path / "all-programs" / "bls_index.parquet"
    combined = write_combined_candidate(
        frames, INITIAL_PROGRAMS, output, dictionary_path=DICTIONARY
    )
    actual = pl.read_parquet(output)
    assert actual.schema == CANONICAL_SCHEMA
    assert actual.height == combined.height
    assert {
        (program, series_id): title
        for program, series_id, title in actual.select(
            "program", "series_id", "series_title"
        ).iter_rows()
    } == titles


def test_candidate_writer_rejects_year_below_four_digit_range_without_output(tmp_path):
    output = tmp_path / "invalid-year" / "bls_index.parquet"
    with pytest.raises(CombinedCandidateError, match="four-digit year range"):
        write_combined_candidate(
            {"ap": _frame(begin_year=999)}, ["ap"], output, dictionary_path=DICTIONARY
        )
    assert not output.exists()


def test_candidate_writer_runs_pinned_cli_from_external_cwd_with_relative_output(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    relative_output = Path("relative") / "bls_index.parquet"
    write_combined_candidate(
        {"ap": _frame()}, ["ap"], relative_output, dictionary_path=DICTIONARY
    )
    assert relative_output.is_file()
    assert pl.read_parquet(relative_output).get_column("program").item() == "ap"

    original = relative_output.read_bytes()
    with pytest.raises(CombinedCandidateError, match="already exists"):
        write_combined_candidate(
            {"ap": _frame(series_id="APU0000701112")},
            ["ap"],
            relative_output,
            dictionary_path=DICTIONARY,
        )
    assert relative_output.read_bytes() == original


def test_candidate_writer_rejects_existing_destination_and_noncanonical_name(tmp_path):
    existing = tmp_path / "bls_index.parquet"
    existing.write_bytes(b"keep")
    with pytest.raises(CombinedCandidateError, match="already exists"):
        write_combined_candidate({"ap": _frame()}, ["ap"], existing, dictionary_path=DICTIONARY)
    assert existing.read_bytes() == b"keep"

    with pytest.raises(CombinedCandidateError, match="canonical bls_index.parquet"):
        write_combined_candidate(
            {"ap": _frame()}, ["ap"], tmp_path / "other.parquet", dictionary_path=DICTIONARY
        )
