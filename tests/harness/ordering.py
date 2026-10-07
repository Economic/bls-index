"""Assertions over the ordered event log."""

from __future__ import annotations

from collections.abc import Iterable

from bls_index.events import Event


def assert_readback_precedes_manifest(events: Iterable[Event], manifest_key: str) -> None:
    """Every immutable object put before a committed manifest write must have a
    successful read-back between its put and that write, and no failed read-back.

    Raises AssertionError naming the first violation.
    """
    pending: dict[str, int] = {}  # key -> seq of the put still awaiting verification
    failed: dict[str, int] = {}
    saw_manifest = False
    for e in events:
        if e.kind == "object.put_immutable":
            pending[e.data["key"]] = e.seq
            failed.pop(e.data["key"], None)
        elif e.kind == "object.readback":
            key = e.data["key"]
            if e.data["ok"]:
                pending.pop(key, None)
            else:
                failed[key] = e.seq
        elif e.kind == "object.put_conditional" and e.data["key"] == manifest_key:
            if e.data["outcome"] == "rejected":
                continue
            saw_manifest = True
            if pending:
                raise AssertionError(
                    f"manifest write at seq {e.seq} precedes read-back of {sorted(pending)}"
                )
            if failed:
                raise AssertionError(
                    f"manifest write at seq {e.seq} follows failed read-back of {sorted(failed)}"
                )
    if not saw_manifest:
        raise AssertionError(f"no manifest write to {manifest_key!r} was recorded")
