"""Assertions over the ordered event log."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from bls_index.events import Event


def assert_readback_precedes_manifest(
    events: Iterable[Event], manifest_key: str, *referenced: Mapping[str, str]
) -> None:
    """Before every dispatched write to ``manifest_key``, every object that write
    references must have a successful read-back with the expected SHA-256.

    Pass one mapping per dispatched write, in order. Each maps the object keys that
    write points to (new uploads and reused last-good files alike) to their expected
    SHA-256. A read-back counts only if it follows the key's most recent upload and no
    read-back of that key failed afterwards. Writes rejected by a failed precondition
    did not dispatch a change and are ignored; ``unknown`` outcomes may have committed
    and count as writes.

    Raises AssertionError naming the first violation, including a mismatch between the
    number of dispatched writes and reference sets.
    """
    if not referenced or not all(referenced):
        raise ValueError("pass one non-empty reference set per manifest write")
    verified: dict[str, str | None] = {}  # key -> SHA-256 last verified, None if stale
    writes = 0
    for e in events:
        key = e.data.get("key")
        if e.kind == "object.put_immutable":
            verified[key] = None
        elif e.kind == "object.readback":
            verified[key] = e.data.get("actual_sha256") if e.data["ok"] else None
        elif e.kind == "object.put_conditional" and key == manifest_key:
            if e.data["outcome"] == "rejected":
                continue
            if writes >= len(referenced):
                raise AssertionError(
                    f"manifest write at seq {e.seq} has no expected reference set "
                    f"({len(referenced)} given)"
                )
            expected = referenced[writes]
            missing = sorted(k for k, sha in expected.items() if verified.get(k) != sha)
            if missing:
                raise AssertionError(
                    f"manifest write {writes + 1} at seq {e.seq} precedes verified "
                    f"read-back of {missing}"
                )
            writes += 1
    if writes != len(referenced):
        raise AssertionError(
            f"expected {len(referenced)} manifest write(s) to {manifest_key!r}, saw {writes}"
        )
