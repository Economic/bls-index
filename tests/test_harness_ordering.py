"""The read-back-before-manifest ordering assertion, exercised through real adapters."""

from __future__ import annotations

import pytest

from bls_index.object_store import ChecksumMismatch, sha256_hex
from tests.harness.ordering import assert_readback_precedes_manifest
from tests.harness.s3 import CORRUPT_BODY, DROP_AFTER, FaultRule

PARQUET = "application/vnd.apache.parquet"
JSON = "application/json"
OBJECTS = {"programs/ap-1.parquet": b"ap bytes", "bls_index-1.parquet": b"combined bytes"}
REFERENCED = {key: sha256_hex(body) for key, body in OBJECTS.items()}
LAST_GOOD = ("programs/pr-0.parquet", b"pr last-good bytes")


def upload_all(store):
    for key, body in OBJECTS.items():
        store.put_immutable(key, body, PARQUET)


def verify_all(store):
    for key, body in OBJECTS.items():
        store.verify(key, sha256_hex(body), len(body))


def write_manifest(store):
    store.put_conditional("latest.json", b"{}", JSON, if_absent=True)


def test_correct_order_passes(store, events):
    upload_all(store)
    verify_all(store)
    write_manifest(store)
    assert_readback_precedes_manifest(events.events, "latest.json", REFERENCED)


def test_manifest_before_readback_is_detected(store, events):
    upload_all(store)
    write_manifest(store)
    verify_all(store)
    with pytest.raises(AssertionError, match="precedes verified read-back"):
        assert_readback_precedes_manifest(events.events, "latest.json", REFERENCED)


def test_partial_readback_is_detected(store, events):
    upload_all(store)
    store.verify("programs/ap-1.parquet", REFERENCED["programs/ap-1.parquet"])
    write_manifest(store)
    with pytest.raises(AssertionError, match="bls_index-1.parquet"):
        assert_readback_precedes_manifest(events.events, "latest.json", REFERENCED)


def test_failed_readback_then_manifest_is_detected(store, events, fault_proxy):
    upload_all(store)
    fault_proxy.add(FaultRule("GET", "bls_index-1.parquet", CORRUPT_BODY))
    with pytest.raises(ChecksumMismatch):
        verify_all(store)
    write_manifest(store)
    with pytest.raises(AssertionError, match="bls_index-1.parquet"):
        assert_readback_precedes_manifest(events.events, "latest.json", REFERENCED)


def test_unknown_manifest_outcome_counts_as_a_write(store, events, fault_proxy):
    """A dispatched write with a lost response may have committed, so ordering applies."""
    upload_all(store)
    fault_proxy.add(FaultRule("PUT", "latest.json", DROP_AFTER))
    write_manifest(store)
    with pytest.raises(AssertionError, match="precedes verified read-back"):
        assert_readback_precedes_manifest(events.events, "latest.json", REFERENCED)


def test_referenced_object_without_upload_or_readback_is_detected(store, events):
    """A reused last-good file is referenced but not uploaded in this run."""
    upload_all(store)
    verify_all(store)
    write_manifest(store)
    referenced = {**REFERENCED, LAST_GOOD[0]: sha256_hex(LAST_GOOD[1])}
    with pytest.raises(AssertionError, match="pr-0.parquet"):
        assert_readback_precedes_manifest(events.events, "latest.json", referenced)


def test_verified_last_good_object_without_upload_passes(store, events, backdoor, bucket):
    backdoor.put_object(Bucket=bucket, Key="test-ns/" + LAST_GOOD[0], Body=LAST_GOOD[1])
    upload_all(store)
    verify_all(store)
    store.verify(LAST_GOOD[0], sha256_hex(LAST_GOOD[1]))
    write_manifest(store)
    referenced = {**REFERENCED, LAST_GOOD[0]: sha256_hex(LAST_GOOD[1])}
    assert_readback_precedes_manifest(events.events, "latest.json", referenced)


def test_readback_of_different_checksum_is_detected(store, events):
    """A successful read-back proves nothing if it checked another checksum."""
    upload_all(store)
    verify_all(store)
    write_manifest(store)
    wrong = {**REFERENCED, "bls_index-1.parquet": sha256_hex(b"other bytes")}
    with pytest.raises(AssertionError, match="bls_index-1.parquet"):
        assert_readback_precedes_manifest(events.events, "latest.json", wrong)


def test_missing_manifest_write_is_detected(store, events):
    upload_all(store)
    verify_all(store)
    with pytest.raises(AssertionError, match="no manifest write"):
        assert_readback_precedes_manifest(events.events, "latest.json", REFERENCED)
