"""The read-back-before-manifest ordering assertion, exercised through real adapters."""

from __future__ import annotations

import pytest

from bls_index.object_store import ChecksumMismatch, sha256_hex
from tests.harness.ordering import assert_readback_precedes_manifest
from tests.harness.s3 import CORRUPT_BODY, DROP_AFTER, FaultRule

PARQUET = "application/vnd.apache.parquet"
OBJECTS = {"programs/ap-1.parquet": b"ap bytes", "bls_index-1.parquet": b"combined bytes"}


def upload_all(store):
    for key, body in OBJECTS.items():
        store.put_immutable(key, body, PARQUET)


def verify_all(store):
    for key, body in OBJECTS.items():
        store.verify(key, sha256_hex(body), len(body))


def test_correct_order_passes(store, events):
    upload_all(store)
    verify_all(store)
    store.put_conditional("latest.json", b"{}", "application/json", if_absent=True)
    assert_readback_precedes_manifest(events.events, "latest.json")


def test_manifest_before_readback_is_detected(store, events):
    upload_all(store)
    store.put_conditional("latest.json", b"{}", "application/json", if_absent=True)
    verify_all(store)
    with pytest.raises(AssertionError, match="precedes read-back"):
        assert_readback_precedes_manifest(events.events, "latest.json")


def test_partial_readback_is_detected(store, events):
    upload_all(store)
    store.verify("programs/ap-1.parquet", sha256_hex(OBJECTS["programs/ap-1.parquet"]))
    store.put_conditional("latest.json", b"{}", "application/json", if_absent=True)
    with pytest.raises(AssertionError, match="bls_index-1.parquet"):
        assert_readback_precedes_manifest(events.events, "latest.json")


def test_failed_readback_then_manifest_is_detected(store, events, fault_proxy):
    upload_all(store)
    fault_proxy.add(FaultRule("GET", "bls_index-1.parquet", CORRUPT_BODY))
    with pytest.raises(ChecksumMismatch):
        verify_all(store)
    store.put_conditional("latest.json", b"{}", "application/json", if_absent=True)
    with pytest.raises(AssertionError):
        assert_readback_precedes_manifest(events.events, "latest.json")


def test_unknown_manifest_outcome_counts_as_a_write(store, events, fault_proxy):
    """A dispatched write with a lost response may have committed, so ordering applies."""
    upload_all(store)
    fault_proxy.add(FaultRule("PUT", "latest.json", DROP_AFTER))
    store.put_conditional("latest.json", b"{}", "application/json", if_absent=True)
    with pytest.raises(AssertionError, match="precedes read-back"):
        assert_readback_precedes_manifest(events.events, "latest.json")


def test_missing_manifest_write_is_detected(store, events):
    upload_all(store)
    verify_all(store)
    with pytest.raises(AssertionError, match="no manifest write"):
        assert_readback_precedes_manifest(events.events, "latest.json")
