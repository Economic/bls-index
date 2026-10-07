"""Assertions over the ordered event log."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from bls_index.events import Event


def assert_readback_precedes_manifest(
    events: Iterable[Event], manifest_key: str, referenced: Mapping[str, str]
) -> None:
    """Before the first dispatched write to ``manifest_key``, every object the manifest
    references must have a successful read-back with the expected SHA-256.

    ``referenced`` maps each object key the manifest will point to (new uploads and
    reused last-good files alike) to its expected SHA-256. A read-back counts only if it
    follows the key's most recent upload and nothing failed for that key afterwards.
    Writes rejected by a failed precondition did not dispatch a change and are ignored;
    ``unknown`` outcomes may have committed and count as writes.

    Raises AssertionError naming the first violation.
    """
    if not referenced:
        raise ValueError("a manifest must reference at least one object")
    verified: dict[str, bool] = {}
    for e in events:
        key = e.data.get("key")
        if e.kind == "object.put_immutable":
            verified[key] = False
        elif e.kind == "object.readback" and key in referenced:
            verified[key] = bool(e.data["ok"]) and e.data.get("actual_sha256") == referenced[key]
        elif e.kind == "object.put_conditional" and key == manifest_key:
            if e.data["outcome"] == "rejected":
                continue
            missing = sorted(k for k in referenced if not verified.get(k))
            if missing:
                raise AssertionError(
                    f"manifest write at seq {e.seq} precedes verified read-back of {missing}"
                )
            return
    raise AssertionError(f"no manifest write to {manifest_key!r} was recorded")
