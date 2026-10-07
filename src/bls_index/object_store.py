"""S3-compatible object store adapter (Cloudflare R2 in staging/production).

The adapter classifies results conservatively:

- Reads distinguish a *confirmed absence* (an explicit 404 for the key) from every other
  failure. 403, 5xx, timeouts, dropped connections and short bodies are errors, never
  absence.
- Conditional writes are ``committed`` only on a 2xx response and ``rejected`` only when
  the store reports a failed precondition. Everything else, including a dropped response
  after the request may have reached storage, is ``unknown`` and must be reconciled by
  the caller.

botocore's automatic retries are disabled: a retried conditional write whose first
attempt committed would come back as a precondition failure and be misread as a
rejection. Callers own retry policy.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from bls_index.events import EventLog


class WriteOutcome(StrEnum):
    COMMITTED = "committed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class WriteResult:
    key: str
    outcome: WriteOutcome
    etag: str | None = None
    status: int | None = None
    error_code: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    etag: str
    size: int


@dataclass(frozen=True)
class StoredObject:
    key: str
    etag: str
    body: bytes


class ObjectNotFound(Exception):
    """The store authoritatively reported that the key does not exist."""


class ObjectStoreError(Exception):
    """A failed or ambiguous operation. Never evidence of absence."""


class ChecksumMismatch(ObjectStoreError):
    pass


def make_s3_client(
    endpoint_url: str,
    access_key_id: str,
    secret_access_key: str,
    *,
    region: str = "auto",
    connect_timeout: float = 10.0,
    read_timeout: float = 60.0,
) -> Any:
    config = Config(
        s3={"addressing_style": "path"},
        retries={"total_max_attempts": 1, "mode": "standard"},  # no automatic retries
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        # Send/verify flexible checksums only when an operation requires them; R2 and
        # local test stores differ in support for boto3's newer defaults.
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region,
        config=config,
    )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class S3ObjectStore:
    """Keys passed to methods are logical; ``prefix`` scopes them to one namespace."""

    def __init__(self, client: Any, bucket: str, prefix: str, events: EventLog) -> None:
        if not prefix or not prefix.endswith("/") or prefix.startswith("/"):
            raise ValueError("prefix must be a non-empty relative namespace ending in '/'")
        self._client = client
        self.bucket = bucket
        self.prefix = prefix
        self._events = events

    def _key(self, key: str) -> str:
        if not key or key.startswith("/"):
            raise ValueError(f"invalid object key {key!r}")
        return self.prefix + key

    # -- writes --------------------------------------------------------------------

    def put_immutable(self, key: str, body: bytes, content_type: str) -> WriteResult:
        """Create-if-absent. ``rejected`` means the key already exists; either way the
        caller must read back and checksum-verify before referencing the object."""
        return self._put("object.put_immutable", key, body, content_type, {"IfNoneMatch": "*"})

    def put_conditional(
        self,
        key: str,
        body: bytes,
        content_type: str,
        *,
        if_match: str | None = None,
        if_absent: bool = False,
    ) -> WriteResult:
        """Replace ``key`` only if its current ETag is ``if_match``, or create it only if
        it is absent. Exactly one condition is required."""
        if (if_match is None) == (not if_absent):
            raise ValueError("specify exactly one of if_match or if_absent")
        condition = {"IfMatch": if_match} if if_match is not None else {"IfNoneMatch": "*"}
        return self._put("object.put_conditional", key, body, content_type, condition)

    def _put(
        self, kind: str, key: str, body: bytes, content_type: str, condition: dict[str, str]
    ) -> WriteResult:
        try:
            resp = self._client.put_object(
                Bucket=self.bucket, Key=self._key(key), Body=body,
                ContentType=content_type, **condition,
            )  # fmt: skip
            result = WriteResult(
                key, WriteOutcome.COMMITTED, etag=resp.get("ETag"),
                status=resp["ResponseMetadata"]["HTTPStatusCode"],
            )  # fmt: skip
        except ClientError as exc:
            status, code = _client_error(exc)
            if status == 412 or code == "PreconditionFailed":
                outcome = WriteOutcome.REJECTED
            elif "IfMatch" in condition and status == 404 and code == "NoSuchKey":
                outcome = WriteOutcome.REJECTED  # If-Match against a missing key
            else:
                outcome = WriteOutcome.UNKNOWN
            result = WriteResult(key, outcome, status=status, error_code=code, detail=str(exc))
        except BotoCoreError as exc:
            result = WriteResult(key, WriteOutcome.UNKNOWN, detail=repr(exc))
        self._events.record(
            kind, key=key, sha256=sha256_hex(body), bytes=len(body),
            condition=sorted(condition), outcome=str(result.outcome),
            status=result.status, error_code=result.error_code,
        )  # fmt: skip
        return result

    # -- reads ---------------------------------------------------------------------

    def stat(self, key: str) -> ObjectInfo:
        """Metadata lookup. Raises ``ObjectNotFound`` only when a follow-up GET confirms
        ``NoSuchKey``."""
        try:
            resp = self._client.head_object(Bucket=self.bucket, Key=self._key(key))
        except ClientError as exc:
            status, code = _client_error(exc)
            self._events.record("object.stat", key=key, result="error", status=status)
            if status != 404:
                raise ObjectStoreError(f"stat {key}: {status} {code}") from exc
            # A HEAD 404 has no error body: it may mean a missing bucket or be spurious.
            # Only a GET that explicitly reports NoSuchKey confirms absence.
            try:
                self.read(key)
            except ObjectNotFound:
                raise
            except ObjectStoreError as read_exc:
                raise ObjectStoreError(f"stat {key}: HEAD 404, then {read_exc}") from exc
            raise ObjectStoreError(
                f"stat {key}: HEAD reported 404 but GET found the object"
            ) from exc
        except BotoCoreError as exc:
            self._events.record("object.stat", key=key, result="error", status=None)
            raise ObjectStoreError(f"stat {key}: {exc!r}") from exc
        info = ObjectInfo(key, resp["ETag"], resp["ContentLength"])
        self._events.record("object.stat", key=key, result="found", etag=info.etag)
        return info

    def read(self, key: str) -> StoredObject:
        """Full-body read. Raises ``ObjectNotFound`` only on an explicit 404."""
        try:
            resp = self._client.get_object(Bucket=self.bucket, Key=self._key(key))
            body = resp["Body"].read()
        except ClientError as exc:
            status, code = _client_error(exc)
            if status == 404 and code == "NoSuchKey":
                self._events.record("object.get", key=key, result="absent", status=status)
                raise ObjectNotFound(key) from exc
            self._events.record("object.get", key=key, result="error", status=status)
            raise ObjectStoreError(f"read {key}: {status} {code}") from exc
        except BotoCoreError as exc:
            self._events.record("object.get", key=key, result="error", status=None)
            raise ObjectStoreError(f"read {key}: {exc!r}") from exc
        expected = resp.get("ContentLength")
        if expected is not None and expected != len(body):
            self._events.record("object.get", key=key, result="incomplete", status=200)
            raise ObjectStoreError(f"read {key}: received {len(body)} of {expected} bytes")
        self._events.record("object.get", key=key, result="found", etag=resp.get("ETag"))
        return StoredObject(key, resp.get("ETag", ""), body)

    def verify(self, key: str, sha256: str, size: int | None = None) -> ObjectInfo:
        """Read back ``key`` and require its SHA-256 (and size, if given) to match."""
        try:
            obj = self.read(key)
        except (ObjectNotFound, ObjectStoreError) as exc:
            self._events.record("object.readback", key=key, ok=False, error=type(exc).__name__)
            raise
        actual = sha256_hex(obj.body)
        ok = actual == sha256 and (size is None or size == len(obj.body))
        self._events.record(
            "object.readback", key=key, ok=ok, expected_sha256=sha256, actual_sha256=actual
        )
        if not ok:
            raise ChecksumMismatch(
                f"{key}: expected sha256 {sha256} ({size} bytes), "
                f"got {actual} ({len(obj.body)} bytes)"
            )
        return ObjectInfo(key, obj.etag, len(obj.body))


def _client_error(exc: ClientError) -> tuple[int | None, str | None]:
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    code = exc.response.get("Error", {}).get("Code")
    return status, code
