from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

import bls_index.native_parquet as native_parquet
from bls_index.http_source import DownloadRecord, InputSet
from bls_index.synthesized_builders import JT_INPUT_NAMES, PR_INPUT_NAMES, SM_INPUT_NAMES
from bls_index.synthesized_parquet import (
    SynthesizedParquetBuildError,
    build_synthesized_parquet,
)
from tests.harness.clock import FakeClock

FIXTURES = Path(__file__).parent / "fixtures" / "real_synthesized"
BUILD_TIME = datetime(2026, 10, 7, 12, 34, 56, 123456, tzinfo=UTC)
PROGRAMS = (("sm", SM_INPUT_NAMES), ("jt", JT_INPUT_NAMES), ("pr", PR_INPUT_NAMES))


def _input_set(tmp_path: Path, program: str, names: tuple[str, ...]) -> InputSet:
    records = []
    rechecks = []
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        fixture_root = (
            Path(__file__).parent / "fixtures" / "two_program" / "pr"
            if program == "pr"
            else FIXTURES / program
        )
        path.write_bytes((fixture_root / name).read_bytes())
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        url = f"https://download.bls.gov/pub/time.series/{program}/{name}"
        records.append(DownloadRecord(url, path, 200, len(body), digest, {}, BUILD_TIME, BUILD_TIME, 1))
        rechecks.append(DownloadRecord(url, None, 200, len(body), digest, {}, BUILD_TIME, BUILD_TIME, 1))
    return InputSet(program, tuple(records), tuple(rechecks), 1)


@pytest.mark.parametrize(("program", "names"), PROGRAMS)
def test_synthesized_bundle_records_every_input_and_roundtrips(tmp_path, program, names):
    input_set = _input_set(tmp_path / "inputs", program, names)
    result = build_synthesized_parquet(input_set, tmp_path / "builds", FakeClock(BUILD_TIME))

    assert result.program == program
    assert result.row_count > 0
    restored = pl.read_parquet(result.parquet_path)
    assert restored.height == result.row_count
    assert restored.get_column("program").unique().to_list() == [program]
    assert restored.get_column("title_source").unique().to_list() == ["synthesized"]
    provenance = json.loads(result.provenance_path.read_text(encoding="utf-8"))
    assert provenance["schema_version"] == 1
    assert provenance["program"] == program
    assert provenance["row_count"] == result.row_count
    assert provenance["source_built_at"] == "2026-10-07T12:34:56.123456Z"
    assert provenance["inputs"] == [
        {"url": record.url, "bytes": record.bytes, "sha256": record.sha256}
        for record in input_set.files
    ]
    assert provenance["artifact"]["compression"] == "zstd"
    assert result.provenance_path.parent.name == result.provenance_sha256
    assert build_synthesized_parquet(input_set, tmp_path / "builds", FakeClock(BUILD_TIME)) == result


@pytest.mark.parametrize("change", ("duplicate", "missing"))
def test_invalid_recheck_set_is_rejected_before_output(tmp_path, change):
    program, names = PROGRAMS[0]
    input_set = _input_set(tmp_path / "inputs", program, names)
    rechecks = list(input_set.rechecks)
    if change == "duplicate":
        rechecks[-1] = rechecks[0]
    else:
        rechecks.pop()
    invalid = InputSet(program, input_set.files, tuple(rechecks), input_set.attempts)

    with pytest.raises(SynthesizedParquetBuildError, match="exactly these inputs|duplicate"):
        build_synthesized_parquet(invalid, tmp_path / "output", FakeClock(BUILD_TIME))
    assert not (tmp_path / "output").exists()


def test_actual_download_bytes_must_match_record(tmp_path):
    program, names = PROGRAMS[1]
    input_set = _input_set(tmp_path / "inputs", program, names)
    source = input_set.files[0].path
    assert source is not None
    source.write_bytes(source.read_bytes() + b"tamper")

    with pytest.raises(SynthesizedParquetBuildError, match="snapshot changed or disagrees"):
        build_synthesized_parquet(input_set, tmp_path / "output", FakeClock(BUILD_TIME))
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("reuse", (False, True))
def test_source_mutation_after_output_staging_fails_new_and_reused_build(
    monkeypatch, tmp_path, reuse
):
    program, names = PROGRAMS[2]
    input_set = _input_set(tmp_path / "inputs", program, names)
    output_dir = tmp_path / "output"
    clock = FakeClock(BUILD_TIME)
    if reuse:
        build_synthesized_parquet(input_set, output_dir, clock)

    source = input_set.files[0].path
    assert source is not None
    real_write = pl.DataFrame.write_parquet

    def write_then_mutate(frame, file, **kwargs):
        result = real_write(frame, file, **kwargs)
        source.write_bytes(source.read_bytes() + b"changed")
        return result

    monkeypatch.setattr(pl.DataFrame, "write_parquet", write_then_mutate)
    with pytest.raises(SynthesizedParquetBuildError, match="after output staging"):
        build_synthesized_parquet(input_set, output_dir, clock)
    assert not list((output_dir / program).glob(".native-build-*"))
    if reuse:
        assert len([item for item in (output_dir / program).iterdir() if item.is_dir()]) == 1
    else:
        assert not (output_dir / program).exists()


def test_corrupt_existing_synthesized_bundle_is_not_reused(tmp_path):
    program, names = PROGRAMS[0]
    input_set = _input_set(tmp_path / "inputs", program, names)
    output_dir = tmp_path / "output"
    first = build_synthesized_parquet(input_set, output_dir, FakeClock(BUILD_TIME))
    first.parquet_path.write_bytes(b"corrupted")

    with pytest.raises(SynthesizedParquetBuildError, match="already exists and does not match"):
        build_synthesized_parquet(input_set, output_dir, FakeClock(BUILD_TIME))
    assert first.parquet_path.read_bytes() == b"corrupted"


def test_racing_synthesized_bundle_is_not_replaced(monkeypatch, tmp_path):
    program, names = PROGRAMS[1]
    input_set = _input_set(tmp_path / "inputs", program, names)
    output_dir = tmp_path / "output"
    real_publish = native_parquet._rename_directory_noreplace
    marker = "competitor owns this bundle"

    def race(source, destination):
        destination.mkdir()
        (destination / "marker.txt").write_text(marker, encoding="utf-8")
        real_publish(source, destination)

    monkeypatch.setattr(native_parquet, "_rename_directory_noreplace", race)
    with pytest.raises(SynthesizedParquetBuildError, match="concurrently created and does not match"):
        build_synthesized_parquet(input_set, output_dir, FakeClock(BUILD_TIME))

    destination = next((output_dir / program).iterdir())
    assert (destination / "marker.txt").read_text(encoding="utf-8") == marker
    assert sorted(item.name for item in destination.iterdir()) == ["marker.txt"]
    assert not list((output_dir / program).glob(".native-build-*"))
