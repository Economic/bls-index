from __future__ import annotations

import json
from pathlib import Path

import pytest

from bls_index.native_builders import NativeSeriesError, parse_native_series, valid_series_id
from bls_index.scope import NATIVE_TITLE_PROGRAMS

FIXTURES = Path(__file__).parent / "fixtures" / "real_native"


def test_manifest_full_file_failures_match_program_records():
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    expected_failures = []
    for program in manifest["programs"]:
        metadata = json.loads((FIXTURES / f"{program}.json").read_text(encoding="utf-8"))
        full_parse = metadata["full_file_parse"]
        if full_parse["status"] != "ok":
            expected_failures.append({"program": program, **full_parse})
    assert manifest["full_file_parse_failures"] == expected_failures
    assert [entry["program"] for entry in expected_failures] == ["cu", "cw"]
    assert manifest["full_file_parse_failures_are_historical"] is True
    revalidated = manifest["current_full_file_revalidations"]
    assert set(revalidated) == {"cu", "cw"}
    for program, record in revalidated.items():
        metadata = json.loads((FIXTURES / f"{program}.json").read_text(encoding="utf-8"))
        assert record == metadata["current_full_file_revalidation"]
        assert record["status"] == "ok"
        assert record["row_count"] == metadata["source_row_count"]
        assert record["sha256"] == record["recheck_sha256"]


@pytest.mark.parametrize("program", NATIVE_TITLE_PROGRAMS)
def test_two_read_verified_real_samples_match_recorded_outputs(program, tmp_path):
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    metadata = json.loads((FIXTURES / f"{program}.json").read_text(encoding="utf-8"))
    sample_path = FIXTURES / f"{program}.series"
    supplemental = metadata.get("supplemental_period_rows", [])
    assert manifest["programs"] == list(NATIVE_TITLE_PROGRAMS)
    assert metadata["program"] == program
    assert metadata["source_row_count"] > 0
    last_source_row = metadata["source_row_count"] + 1
    assert metadata["source_rows_1based"] == sorted(
        {2, metadata["source_row_count"] // 2 + 2, last_source_row}
    )
    assert metadata["source_rows_1based"] == [
        row["source_row_1based"] for row in metadata["sample_rows"]
    ]
    assert all(
        valid_series_id(row["raw_fields"][0].strip(), program)
        for row in metadata["sample_rows"]
    )
    assert all(2 <= row <= metadata["source_row_count"] + 1 for row in metadata["source_rows_1based"])
    if program in {"cu", "cw"}:
        assert metadata["period_contract_source"]["url"].endswith(f"/{program}.txt")
        assert (
            metadata["period_contract_source"]["sha256"]
            == metadata["period_contract_source"]["recheck_sha256"]
        )
        assert {
            code
            for row in supplemental
            for code in row["period_codes"]
        } >= {"S01", "S02", "S03"}
        assert metadata["current_full_file_revalidation"]["status"] == "ok"
    assert metadata["url"].endswith(f"/{program}/{program}.series")
    assert metadata["two_read_sha256_match"] is True
    assert metadata["sha256"] == metadata["recheck_sha256"]
    assert metadata["sample_sha256"] == __import__("hashlib").sha256(
        sample_path.read_bytes()
    ).hexdigest()
    assert metadata["source_rows_1based"]
    assert "User-Agent" not in json.dumps(metadata)

    lines = sample_path.read_text(encoding="utf-8").splitlines()
    expected_rows = metadata["sample_rows"] + supplemental
    assert len(lines) == len(expected_rows) + 1
    assert lines[0].split("\t")
    for index, (line, expected) in enumerate(zip(lines[1:], expected_rows, strict=True)):
        assert line.split("\t") == expected["raw_fields"]
        one_row_path = tmp_path / f"{program}-{index}.series"
        one_row_path.write_text(lines[0] + "\n" + line + "\n", encoding="utf-8")
        if expected.get("parse_status", "ok") == "ok":
            frame = parse_native_series(one_row_path, program)
            assert frame.row(0, named=True) == expected["expected_canonical"]
            assert frame.get_column("series_title").item() == expected["raw_fields"][
                lines[0].split("\t").index("series_title")
            ]
        else:
            with pytest.raises(NativeSeriesError) as caught:
                parse_native_series(one_row_path, program)
            stable_error = expected["expected_error"]["error"].split(": ", 1)[-1]
            assert stable_error in str(caught.value)
