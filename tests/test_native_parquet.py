from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

import bls_index.native_parquet as native_parquet
from bls_index.http_source import DownloadRecord, InputSet
from bls_index.native_builders import parse_native_series
from bls_index.native_parquet import NativeParquetBuildError, build_native_parquet
from tests.harness.clock import FakeClock

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "native"
BUILD_TIME = datetime(2026, 10, 7, 12, 34, 56, 123456, tzinfo=UTC)


def _input_set(path: Path, program: str = "ap", *, expected_bytes: bytes | None = None) -> InputSet:
    body = expected_bytes if expected_bytes is not None else path.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    url = f"https://download.bls.gov/pub/time.series/{program}/{program}.series"
    downloaded = DownloadRecord(
        url=url, path=path, status=200, bytes=len(body), sha256=digest,
        headers={}, started_at=BUILD_TIME, finished_at=BUILD_TIME, request_attempts=1,
    )
    recheck = DownloadRecord(
        url=url, path=None, status=200, bytes=len(body), sha256=digest,
        headers={}, started_at=BUILD_TIME, finished_at=BUILD_TIME, request_attempts=1,
    )
    return InputSet(program, (downloaded,), (recheck,), 1)


def test_local_parquet_roundtrip_and_provenance_are_deterministic(tmp_path):
    source_path = FIXTURE_DIR / "ap.series"
    input_set = _input_set(source_path)
    output_dir = tmp_path / "builds"
    clock = FakeClock(BUILD_TIME)

    first = build_native_parquet(input_set, output_dir, clock)
    second = build_native_parquet(input_set, output_dir, clock)

    assert first == second
    assert first.parquet_path.exists()
    assert first.provenance_path.exists()
    restored = pl.read_parquet(first.parquet_path)
    expected = parse_native_series(source_path, "ap")
    assert restored.equals(expected)
    assert restored.height == first.row_count > 0
    assert restored.schema == {
        "program": pl.String,
        "series_id": pl.String,
        "series_title": pl.String,
        "title_source": pl.String,
        "seasonal": pl.String,
        "begin_year": pl.Int32,
        "end_year": pl.Int32,
        "end_period": pl.String,
    }

    provenance = json.loads(first.provenance_path.read_text())
    assert provenance == {
        "schema_version": 1,
        "program": "ap",
        "row_count": first.row_count,
        "source_built_at": "2026-10-07T12:34:56.123456Z",
        "inputs": [{
            "url": input_set.files[0].url,
            "bytes": input_set.files[0].bytes,
            "sha256": input_set.files[0].sha256,
        }],
        "artifact": {
            "path": "catalog.parquet",
            "bytes": first.parquet_bytes,
            "sha256": first.parquet_sha256,
            "compression": "zstd",
        },
    }
    actual = first.parquet_path.read_bytes()
    assert len(actual) == first.parquet_bytes
    assert hashlib.sha256(actual).hexdigest() == first.parquet_sha256
    assert first.provenance_path.parent.name == first.provenance_sha256


def test_actual_input_bytes_must_match_verified_record(tmp_path):
    path = tmp_path / "ap.series"
    path.write_bytes(FIXTURE_DIR.joinpath("ap.series").read_bytes())
    verified_bytes = path.read_bytes()
    input_set = _input_set(path, expected_bytes=verified_bytes)
    path.write_bytes(verified_bytes + b"\n")

    with pytest.raises(NativeParquetBuildError, match="changed or disagrees with verified provenance"):
        build_native_parquet(input_set, tmp_path / "output", FakeClock(BUILD_TIME))
    assert not (tmp_path / "output" / "ap").exists()


def test_source_mutation_during_parse_is_rejected_and_staged_output_removed(monkeypatch, tmp_path):
    source_path = tmp_path / "ap.series"
    source_path.write_bytes(FIXTURE_DIR.joinpath("ap.series").read_bytes())
    input_set = _input_set(source_path)
    real_parse = native_parquet.parse_native_series

    def mutate_after_parse(path, program):
        frame = real_parse(path, program)
        source_path.write_bytes(source_path.read_bytes() + b"\n")
        return frame

    monkeypatch.setattr(native_parquet, "parse_native_series", mutate_after_parse)
    output_dir = tmp_path / "output"
    with pytest.raises(NativeParquetBuildError, match="changed or disagrees with verified provenance"):
        build_native_parquet(input_set, output_dir, FakeClock(BUILD_TIME))
    assert not output_dir.exists()


def test_recheck_record_must_match_download_record(tmp_path):
    path = FIXTURE_DIR / "ap.series"
    input_set = _input_set(path)
    mismatched = DownloadRecord(
        url=input_set.files[0].url, path=None, status=200,
        bytes=input_set.files[0].bytes + 1, sha256=input_set.files[0].sha256,
        headers={}, started_at=BUILD_TIME, finished_at=BUILD_TIME, request_attempts=1,
    )
    invalid = InputSet("ap", input_set.files, (mismatched,), 1)

    with pytest.raises(NativeParquetBuildError, match="download recheck does not match"):
        build_native_parquet(invalid, tmp_path / "output", FakeClock(BUILD_TIME))
    assert not (tmp_path / "output").exists()


def test_unsupported_program_is_rejected(tmp_path):
    path = tmp_path / "bd.series"
    path.write_text("unparsed")
    input_set = _input_set(path, "bd")
    with pytest.raises(NativeParquetBuildError, match="unsupported native program"):
        build_native_parquet(input_set, tmp_path / "output", FakeClock(BUILD_TIME))
    assert not (tmp_path / "output").exists()


def test_existing_unrelated_files_are_not_overwritten(tmp_path):
    path = FIXTURE_DIR / "ap.series"
    output_dir = tmp_path / "output"
    program_dir = output_dir / "ap"
    program_dir.mkdir(parents=True)
    unrelated = program_dir / "notes.txt"
    unrelated.write_text("preserve this")

    result = build_native_parquet(_input_set(path), output_dir, FakeClock(BUILD_TIME))

    assert unrelated.read_text() == "preserve this"
    assert result.parquet_path.is_file()
    assert result.provenance_path.is_file()


def test_parquet_write_failure_cleans_staging_and_new_output_directories(monkeypatch, tmp_path):
    def fail_write(self, file, **kwargs):
        raise OSError("simulated Parquet write failure")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", fail_write)
    output_dir = tmp_path / "output"
    with pytest.raises(NativeParquetBuildError, match="simulated Parquet write failure"):
        build_native_parquet(
            _input_set(FIXTURE_DIR / "ap.series"), output_dir, FakeClock(BUILD_TIME)
        )
    assert not output_dir.exists()
