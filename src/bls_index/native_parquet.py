"""Local Parquet builds for verified native-title program inputs.

This module writes only local, per-program artifacts. It does not fetch data,
publish artifacts, or modify the native parser.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import polars as pl

from bls_index.clock import Clock, isoformat_utc
from bls_index.http_source import DownloadRecord, InputSet
from bls_index.native_builders import (
    CANONICAL_SCHEMA,
    SCHEMA_VERSION,
    SUPPORTED_NATIVE_PROGRAMS,
    NativeSeriesError,
    parse_native_series,
)

_COPY_CHUNK_SIZE = 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RENAME_NOREPLACE = 1


class NativeParquetBuildError(ValueError):
    """A verified native input could not be safely built or published locally."""


@dataclass(frozen=True)
class NativeParquetBuild:
    """Paths and checksums for one locally completed native-program build."""

    program: str
    row_count: int
    parquet_path: Path
    provenance_path: Path
    parquet_bytes: int
    parquet_sha256: str
    provenance_sha256: str
    source_built_at: str


def _record_digest(record: DownloadRecord, label: str) -> None:
    if not isinstance(record.bytes, int) or isinstance(record.bytes, bool) or record.bytes < 0:
        raise NativeParquetBuildError(f"{label} has an invalid byte count")
    if not isinstance(record.sha256, str) or not _SHA256_RE.fullmatch(record.sha256):
        raise NativeParquetBuildError(f"{label} has an invalid SHA-256")
    if record.status != 200:
        raise NativeParquetBuildError(f"{label} is not a successful HTTP 200 response")


def _validate_input_set(input_set: InputSet, program: str) -> tuple[DownloadRecord, Path]:
    if program not in SUPPORTED_NATIVE_PROGRAMS:
        raise NativeParquetBuildError(
            f"unsupported native program {program!r}; supported: {SUPPORTED_NATIVE_PROGRAMS!r}"
        )
    if input_set.program != program:
        raise NativeParquetBuildError(
            f"InputSet program {input_set.program!r} does not match requested program {program!r}"
        )
    if input_set.attempts < 1:
        raise NativeParquetBuildError("InputSet must record at least one verification attempt")
    if len(input_set.files) != 1 or len(input_set.rechecks) != 1:
        raise NativeParquetBuildError(
            "native per-program builds require exactly one verified .series input"
        )

    record, recheck = input_set.files[0], input_set.rechecks[0]
    _record_digest(record, "download record")
    _record_digest(recheck, "download recheck")
    if record.url != recheck.url:
        raise NativeParquetBuildError("download recheck URL does not match the input record")
    if record.sha256 != recheck.sha256 or record.bytes != recheck.bytes:
        raise NativeParquetBuildError("download recheck does not match the input record")

    parsed_url = urlsplit(record.url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise NativeParquetBuildError("input record must have an HTTP(S) source URL")
    url_parts = [part for part in parsed_url.path.split("/") if part]
    if len(url_parts) < 2 or url_parts[-2:] != [program, f"{program}.series"]:
        raise NativeParquetBuildError(
            f"input URL must identify {program}/{program}.series, got {record.url!r}"
        )
    if record.path is None:
        raise NativeParquetBuildError("verified .series input has no local downloaded path")
    return record, Path(record.path)


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(_COPY_CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise NativeParquetBuildError(f"cannot verify input file {path}: {exc}") from exc
    return digest.hexdigest(), size


def _verify_source(path: Path, record: DownloadRecord, phase: str) -> None:
    actual_sha256, actual_bytes = _hash_file(path)
    if actual_sha256 != record.sha256 or actual_bytes != record.bytes:
        raise NativeParquetBuildError(
            f"input file changed or disagrees with verified provenance {phase}: "
            f"expected {record.sha256} ({record.bytes} bytes), "
            f"got {actual_sha256} ({actual_bytes} bytes)"
        )


def _copy_verified_snapshot(source: Path, snapshot: Path, record: DownloadRecord) -> None:
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as source_stream, snapshot.open("xb") as target_stream:
            while chunk := source_stream.read(_COPY_CHUNK_SIZE):
                target_stream.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            target_stream.flush()
    except OSError as exc:
        raise NativeParquetBuildError(f"cannot stage verified input {source}: {exc}") from exc
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != record.sha256 or size != record.bytes:
        raise NativeParquetBuildError(
            "input snapshot changed or disagrees with verified provenance: "
            f"expected {record.sha256} ({record.bytes} bytes), "
            f"got {actual_sha256} ({size} bytes)"
        )


def _hash_artifact(path: Path) -> tuple[str, int]:
    return _hash_file(path)


def _bundle_matches(
    destination: Path, parquet_sha256: str, parquet_bytes: int, provenance_bytes: bytes
) -> bool:
    parquet_path = destination / "catalog.parquet"
    sidecar_path = destination / "provenance.json"
    if not destination.is_dir() or not parquet_path.is_file() or not sidecar_path.is_file():
        return False
    if sidecar_path.read_bytes() != provenance_bytes:
        return False
    actual_sha256, actual_bytes = _hash_artifact(parquet_path)
    return actual_sha256 == parquet_sha256 and actual_bytes == parquet_bytes


def _rename_directory_noreplace(source: Path, destination: Path) -> None:
    """Atomically expose a directory only if its destination name is still absent."""
    if not sys.platform.startswith("linux"):
        raise NativeParquetBuildError(
            "atomic no-replace directory publication is unavailable on this platform"
        )
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise NativeParquetBuildError(
            "atomic no-replace directory publication is unavailable on this system"
        )
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100, os.fsencode(source), -100, os.fsencode(destination), _RENAME_NOREPLACE
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(error_number, os.strerror(error_number), str(destination))
    if error_number in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
        raise NativeParquetBuildError(
            "atomic no-replace directory publication is unavailable on this filesystem"
        )
    raise OSError(error_number, os.strerror(error_number), str(destination))


def build_native_parquet(
    input_set: InputSet,
    output_dir: str | Path,
    clock: Clock,
) -> NativeParquetBuild:
    """Build a local schema-v1 Parquet bundle from an explicitly verified InputSet.

    The InputSet's download and recheck records must agree. Its bytes are copied into a
    private snapshot while hashing; that exact snapshot is checked against the expected
    checksum and parsed. The downloaded path is checked after parsing and after complete
    output staging immediately before publication; this check does not prevent changes after
    that boundary. Output is zstd-compressed and published with an atomic no-replace directory
    operation. The bundle directory is addressed by the SHA-256 of its provenance JSON, so a
    prior build or unrelated file is never overwritten.
    """
    program = input_set.program
    record, source_path = _validate_input_set(input_set, program)
    try:
        _verify_source(source_path, record, "before staging")
        with tempfile.TemporaryDirectory(prefix="bls-native-input-") as source_staging:
            snapshot = Path(source_staging) / "source.series"
            _copy_verified_snapshot(source_path, snapshot, record)
            frame = parse_native_series(snapshot, program)
        if frame.schema != CANONICAL_SCHEMA:
            raise NativeParquetBuildError("native parser returned a non-canonical schema")
        if frame.height < 1:
            raise NativeParquetBuildError("native parser returned no rows")
        _verify_source(source_path, record, "after parsing")
    except NativeSeriesError as exc:
        raise NativeParquetBuildError(str(exc)) from exc

    root = Path(output_dir)
    made_root = not root.exists()
    program_dir = root / program
    made_program_dir = not program_dir.exists()
    staging_dir: Path | None = None
    try:
        _verify_source(source_path, record, "before publication")
        program_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix=".native-build-", dir=program_dir))
        parquet_path = staging_dir / "catalog.parquet"
        frame.write_parquet(parquet_path, compression="zstd")
        parquet_sha256, parquet_bytes = _hash_artifact(parquet_path)
        _verify_source(source_path, record, "before publication")

        # This is the build clock, never a file mtime or source-provided timestamp.
        source_built_at = isoformat_utc(clock.now())
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "program": program,
            "row_count": frame.height,
            "source_built_at": source_built_at,
            "inputs": [
                {"url": record.url, "bytes": record.bytes, "sha256": record.sha256}
            ],
            "artifact": {
                "path": "catalog.parquet",
                "bytes": parquet_bytes,
                "sha256": parquet_sha256,
                "compression": "zstd",
            },
        }
        provenance_bytes = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        provenance_path = staging_dir / "provenance.json"
        with provenance_path.open("xb") as stream:
            stream.write(provenance_bytes)
            stream.flush()
            os.fsync(stream.fileno())

        bundle_sha256 = hashlib.sha256(provenance_bytes).hexdigest()
        destination = program_dir / bundle_sha256
        final_parquet = destination / "catalog.parquet"
        final_provenance = destination / "provenance.json"
        # Verify after the sidecar is complete, before either the existing-bundle
        # success path or a new publication attempt. This boundary cannot prevent
        # later changes to the source.
        _verify_source(source_path, record, "after output staging")
        if destination.exists():
            if not _bundle_matches(destination, parquet_sha256, parquet_bytes, provenance_bytes):
                raise NativeParquetBuildError(
                    f"content-addressed output already exists and does not match: {destination}"
                )
            shutil.rmtree(staging_dir)
            staging_dir = None
            return NativeParquetBuild(
                program, frame.height, final_parquet, final_provenance, parquet_bytes,
                parquet_sha256, bundle_sha256, source_built_at,
            )

        # Establish input provenance at the last check boundary, after both artifacts
        # are complete. This cannot prevent a source change after the check.
        _verify_source(source_path, record, "immediately before publication")
        try:
            _rename_directory_noreplace(staging_dir, destination)
        except FileExistsError:
            # Another builder may have won the name race. Treat it as success only if
            # the entire bundle is exactly the one we intended to publish.
            if not _bundle_matches(destination, parquet_sha256, parquet_bytes, provenance_bytes):
                raise NativeParquetBuildError(
                    f"content-addressed output was concurrently created and does not match: {destination}"
                )
            shutil.rmtree(staging_dir)
            staging_dir = None
        else:
            staging_dir = None
        return NativeParquetBuild(
            program, frame.height, final_parquet, final_provenance, parquet_bytes,
            parquet_sha256, bundle_sha256, source_built_at,
        )
    except NativeParquetBuildError:
        raise
    except Exception as exc:
        raise NativeParquetBuildError(f"native Parquet build failed: {exc}") from exc
    finally:
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)
        if made_program_dir:
            try:
                program_dir.rmdir()
            except OSError:
                pass
        if made_root:
            try:
                root.rmdir()
            except OSError:
                pass
