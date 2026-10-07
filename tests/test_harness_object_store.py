"""Object-store adapter against moto behind the fault-injecting proxy."""

from __future__ import annotations

import pytest

from bls_index.object_store import (
    ChecksumMismatch,
    ObjectNotFound,
    ObjectStoreError,
    S3ObjectStore,
    WriteOutcome,
    make_s3_client,
    sha256_hex,
)
from tests.harness.s3 import (
    CORRUPT_BODY,
    DELAY,
    DROP_AFTER,
    DROP_BEFORE,
    STATUS,
    TRUNCATE_BODY,
    FaultRule,
)

PARQUET = "application/vnd.apache.parquet"
JSON = "application/json"


def stored(backdoor, bucket, key) -> bytes | None:
    try:
        return backdoor.get_object(Bucket=bucket, Key="test-ns/" + key)["Body"].read()
    except backdoor.exceptions.NoSuchKey:
        return None


# -- immutable upload and read-back ---------------------------------------------------


def test_put_immutable_then_verify(store, events):
    body = b"parquet bytes"
    result = store.put_immutable("programs/ap-abc.parquet", body, PARQUET)

    assert result.outcome is WriteOutcome.COMMITTED
    info = store.verify("programs/ap-abc.parquet", sha256_hex(body), len(body))
    assert info.size == len(body)
    assert [e.kind for e in events.events] == ["object.put_immutable", "object.get", "object.readback"]
    assert events.events[-1].data["ok"] is True


def test_put_immutable_existing_key_is_rejected_not_overwritten(store, backdoor, bucket):
    store.put_immutable("k", b"first", PARQUET)
    result = store.put_immutable("k", b"second", PARQUET)

    assert result.outcome is WriteOutcome.REJECTED
    assert stored(backdoor, bucket, "k") == b"first"


def test_namespace_prefix_isolates_keys(store, backdoor, bucket):
    store.put_immutable("latest.json", b"{}", JSON)
    assert stored(backdoor, bucket, "latest.json") == b"{}"
    with pytest.raises(backdoor.exceptions.NoSuchKey):
        backdoor.get_object(Bucket=bucket, Key="latest.json")


@pytest.mark.parametrize("prefix", ["", "no-slash", "/abs/"])
def test_prefix_must_be_relative_namespace(prefix, events):
    with pytest.raises(ValueError):
        S3ObjectStore(object(), "b", prefix, events)


# -- corruption ---------------------------------------------------------------------


def test_stored_corruption_fails_verification(store, backdoor, bucket, events):
    body = b"good bytes"
    store.put_immutable("k", body, PARQUET)
    backdoor.put_object(Bucket=bucket, Key="test-ns/k", Body=b"bad! bytes")

    with pytest.raises(ChecksumMismatch):
        store.verify("k", sha256_hex(body), len(body))
    assert events.events[-1].kind == "object.readback"
    assert events.events[-1].data["ok"] is False


def test_corrupted_response_fails_verification(store, fault_proxy):
    body = b"good bytes"
    store.put_immutable("k", body, PARQUET)
    fault_proxy.add(FaultRule("GET", "/k", CORRUPT_BODY))

    with pytest.raises(ChecksumMismatch):
        store.verify("k", sha256_hex(body))
    store.verify("k", sha256_hex(body))  # the stored object itself is intact


def test_truncated_response_is_an_error(store, fault_proxy):
    store.put_immutable("k", b"0123456789" * 10, PARQUET)
    fault_proxy.add(FaultRule("GET", "/k", TRUNCATE_BODY))

    with pytest.raises(ObjectStoreError) as info:
        store.read("k")
    assert not isinstance(info.value, ObjectNotFound)


def test_size_mismatch_fails_verification(store):
    body = b"abc"
    store.put_immutable("k", body, PARQUET)
    with pytest.raises(ChecksumMismatch):
        store.verify("k", sha256_hex(body), size=4)


# -- confirmed absence versus errors --------------------------------------------------


def test_missing_key_is_confirmed_absence(store):
    with pytest.raises(ObjectNotFound):
        store.read("latest.json")
    with pytest.raises(ObjectNotFound):
        store.stat("latest.json")


@pytest.mark.parametrize(
    ("status", "code"),
    [(403, "AccessDenied"), (500, "InternalError"), (503, "SlowDown"), (404, "NoSuchBucket")],
)
def test_read_errors_are_never_absence(status, code, store, fault_proxy):
    # Persistent faults: a denied or missing bucket fails every request.
    fault_proxy.add(FaultRule("GET", "latest.json", STATUS, status=status, code=code, times=None))
    fault_proxy.add(FaultRule("HEAD", "latest.json", STATUS, status=status, code=code, times=None))

    for op in (store.read, store.stat):
        with pytest.raises(ObjectStoreError) as info:
            op("latest.json")
        assert not isinstance(info.value, ObjectNotFound)


def test_spurious_head_404_for_existing_key_is_not_absence(store, fault_proxy):
    store.put_immutable("latest.json", b"{}", JSON)
    fault_proxy.add(FaultRule("HEAD", "latest.json", STATUS, status=404, code="NoSuchKey"))

    with pytest.raises(ObjectStoreError) as info:
        store.stat("latest.json")
    assert not isinstance(info.value, ObjectNotFound)


def test_head_404_with_failing_confirmation_read_is_not_absence(store, fault_proxy):
    fault_proxy.add(FaultRule("HEAD", "latest.json", STATUS, status=404, code="NoSuchKey"))
    fault_proxy.add(FaultRule("GET", "latest.json", STATUS, status=503, code="SlowDown"))

    with pytest.raises(ObjectStoreError) as info:
        store.stat("latest.json")
    assert not isinstance(info.value, ObjectNotFound)


def test_missing_bucket_head_is_not_absence(fault_proxy, events):
    client = make_s3_client(fault_proxy.url, "testing", "testing", region="us-east-1")
    store = S3ObjectStore(client, "bucket-that-does-not-exist", "ns/", events)
    with pytest.raises(ObjectStoreError) as info:
        store.stat("latest.json")
    assert not isinstance(info.value, ObjectNotFound)
    with pytest.raises(ObjectStoreError) as info:
        store.read("latest.json")
    assert not isinstance(info.value, ObjectNotFound)


@pytest.mark.parametrize("action", [DROP_BEFORE, DROP_AFTER])
def test_dropped_read_is_error(action, store, fault_proxy):
    store.put_immutable("k", b"x", PARQUET)
    fault_proxy.add(FaultRule("GET", "/k", action))
    with pytest.raises(ObjectStoreError) as info:
        store.read("k")
    assert not isinstance(info.value, ObjectNotFound)


def test_read_timeout_is_error(store, fault_proxy):
    store.put_immutable("k", b"x", PARQUET)
    fault_proxy.add(FaultRule("GET", "/k", DELAY, seconds=3.0))
    with pytest.raises(ObjectStoreError):
        store.read("k")


# -- conditional manifest writes ------------------------------------------------------


def test_create_if_absent_then_compare_and_swap(store, backdoor, bucket):
    first = store.put_conditional("latest.json", b'{"v":1}', JSON, if_absent=True)
    assert first.outcome is WriteOutcome.COMMITTED

    again = store.put_conditional("latest.json", b'{"v":"x"}', JSON, if_absent=True)
    assert again.outcome is WriteOutcome.REJECTED

    second = store.put_conditional("latest.json", b'{"v":2}', JSON, if_match=first.etag)
    assert second.outcome is WriteOutcome.COMMITTED

    stale = store.put_conditional("latest.json", b'{"v":"stale"}', JSON, if_match=first.etag)
    assert stale.outcome is WriteOutcome.REJECTED
    assert stale.status == 412
    assert stored(backdoor, bucket, "latest.json") == b'{"v":2}'
    assert store.stat("latest.json").etag == second.etag


def test_if_match_on_missing_key_is_rejected(store, backdoor, bucket):
    result = store.put_conditional("latest.json", b"{}", JSON, if_match='"deadbeef"')
    assert result.outcome is WriteOutcome.REJECTED
    assert stored(backdoor, bucket, "latest.json") is None


def test_if_match_404_without_no_such_key_is_unknown(store, fault_proxy):
    fault_proxy.add(FaultRule("PUT", "latest.json", STATUS, status=404, code="NoSuchBucket"))
    result = store.put_conditional("latest.json", b"{}", JSON, if_match='"deadbeef"')
    assert result.outcome is WriteOutcome.UNKNOWN


def test_conditional_put_requires_exactly_one_condition(store):
    with pytest.raises(ValueError):
        store.put_conditional("latest.json", b"{}", JSON)
    with pytest.raises(ValueError):
        store.put_conditional("latest.json", b"{}", JSON, if_match='"x"', if_absent=True)


def test_commit_then_dropped_response_is_unknown_and_not_retried(store, fault_proxy, backdoor, bucket):
    fault_proxy.add(FaultRule("PUT", "latest.json", DROP_AFTER))
    result = store.put_conditional("latest.json", b'{"v":1}', JSON, if_absent=True)

    assert result.outcome is WriteOutcome.UNKNOWN
    # The write did commit, and the adapter sent exactly one request: an automatic
    # retry would have returned 412 and been misread as a rejection.
    assert stored(backdoor, bucket, "latest.json") == b'{"v":1}'
    assert len(fault_proxy.requests_matching("PUT", "latest.json")) == 1


def test_dropped_request_is_unknown_even_though_nothing_committed(store, fault_proxy, backdoor, bucket):
    fault_proxy.add(FaultRule("PUT", "latest.json", DROP_BEFORE))
    result = store.put_conditional("latest.json", b"{}", JSON, if_absent=True)

    assert result.outcome is WriteOutcome.UNKNOWN
    assert stored(backdoor, bucket, "latest.json") is None


@pytest.mark.parametrize(
    ("status", "code"),
    [(500, "InternalError"), (503, "SlowDown"), (403, "AccessDenied"), (409, "ConditionalRequestConflict")],
)
def test_error_statuses_are_unknown(status, code, store, fault_proxy):
    fault_proxy.add(FaultRule("PUT", "latest.json", STATUS, status=status, code=code))
    result = store.put_conditional("latest.json", b"{}", JSON, if_absent=True)
    assert result.outcome is WriteOutcome.UNKNOWN
    assert (result.status, result.error_code) == (status, code)


def test_write_timeout_is_unknown(store, fault_proxy):
    fault_proxy.add(FaultRule("PUT", "latest.json", DELAY, seconds=3.0))
    result = store.put_conditional("latest.json", b"{}", JSON, if_absent=True)
    assert result.outcome is WriteOutcome.UNKNOWN


def test_write_events_record_outcome(store, fault_proxy, events):
    store.put_conditional("latest.json", b"{}", JSON, if_absent=True)
    fault_proxy.add(FaultRule("PUT", "latest.json", DROP_AFTER))
    store.put_conditional("latest.json", b"{}", JSON, if_absent=True)

    writes = events.of_kind("object.put_conditional")
    assert [w.data["outcome"] for w in writes] == ["committed", "unknown"]
    assert writes[0].data["condition"] == ["IfNoneMatch"]
    assert writes[0].data["sha256"] == sha256_hex(b"{}")
