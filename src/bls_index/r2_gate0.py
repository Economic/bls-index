"""Opt-in, narrowly scoped real-R2 check for the Gate 0 storage assumptions."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bls_index.clock import SystemClock
from bls_index.events import EventLog
from bls_index.object_store import (
    ObjectNotFound,
    S3ObjectStore,
    WriteOutcome,
    WriteResult,
    sha256_hex,
)

STAGING_BUCKET = "bls-index-staging"
_TEST_KEYS = ("immutable.bin", "cas.json", "confirmed-absent.json")
_RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
_ENDPOINT_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*\.r2\.cloudflarestorage\.com\Z")


class Gate0CheckError(Exception):
    """A safe-to-display failure from the real R2 check."""


def validate_r2_endpoint(endpoint: str) -> str:
    """Accept only an HTTPS Cloudflare R2 account endpoint (no path or credentials)."""
    try:
        parsed = urlsplit(endpoint.strip())
        hostname = parsed.hostname
    except (AttributeError, ValueError):
        raise ValueError("enter an HTTPS Cloudflare R2 account endpoint") from None
    if (
        parsed.scheme != "https"
        or hostname is None
        or not _ENDPOINT_PATTERN.fullmatch(hostname.lower())
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("enter an HTTPS Cloudflare R2 account endpoint")
    return f"https://{hostname.lower()}"


def run_r2_gate0(client: object, *, run_id: str | None = None) -> str:
    """Run the real store checks through ``S3ObjectStore``; return the removed prefix.

    ``run_id`` is injectable only to make offline tests deterministic. Normal callers
    use an unpredictable identifier so no existing namespace is intentionally reused.
    """
    if run_id is None:
        import secrets

        run_id = secrets.token_hex(16)
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise Gate0CheckError("Invalid temporary namespace identifier.")

    prefix = f"gate0/{run_id}/"
    events = EventLog(SystemClock())
    store = S3ObjectStore(client, STAGING_BUCKET, prefix, events)
    bodies = {
        "immutable.bin": (b"bls-index Gate0 immutable object v1\n", b"bls-index Gate0 immutable object duplicate\n"),
        "cas.json": (b'{"gate0":"first"}\n', b'{"gate0":"second"}\n', b'{"gate0":"stale"}\n'),
        "confirmed-absent.json": (),
    }
    preflight_complete = False
    submitted_bodies: dict[str, set[bytes]] = {}
    unsettled_keys: set[str] = set()
    failure: str | None = None
    cleanup_failed: list[str] = []

    def submit(write, key: str, body: bytes, *args, **kwargs) -> WriteResult:
        # Track the body before dispatch: a write may change storage even when it reports
        # rejection, and one with an unknown outcome may still land after cleanup.
        submitted_bodies.setdefault(key, set()).add(body)
        result = None
        try:
            result = write(key, body, *args, **kwargs)
        finally:
            if result is None or result.outcome is WriteOutcome.UNKNOWN:
                unsettled_keys.add(key)
        return result

    try:
        # Confirm every exact key is absent before making any write. A HEAD 404 by itself
        # is not enough: S3ObjectStore.stat performs the authoritative follow-up GET.
        for key in _TEST_KEYS:
            try:
                store.stat(key)
            except ObjectNotFound:
                continue
            raise Gate0CheckError("A generated test key already exists; no test was run.")
        preflight_complete = True

        missing_key = "confirmed-absent.json"
        try:
            store.read(missing_key)
        except ObjectNotFound:
            pass
        else:
            raise Gate0CheckError("Confirmed-absence check failed.")
        try:
            store.stat(missing_key)
        except ObjectNotFound:
            pass
        else:
            raise Gate0CheckError("Confirmed-absence check failed.")

        immutable_body, duplicate_body = bodies["immutable.bin"]
        created = submit(store.put_immutable, "immutable.bin", immutable_body, "application/octet-stream")
        if created.outcome is not WriteOutcome.COMMITTED or not created.etag:
            raise Gate0CheckError("Create-if-absent check failed.")
        duplicate_body_result = submit(
            store.put_immutable, "immutable.bin", duplicate_body, "application/octet-stream"
        )
        if duplicate_body_result.outcome is not WriteOutcome.REJECTED:
            raise Gate0CheckError("Duplicate create-if-absent check failed.")
        store.verify("immutable.bin", sha256_hex(immutable_body), len(immutable_body))

        first_body, second_body, stale_body = bodies["cas.json"]
        first = submit(store.put_conditional, "cas.json", first_body, "application/json", if_absent=True)
        if first.outcome is not WriteOutcome.COMMITTED or not first.etag:
            raise Gate0CheckError("Conditional create check failed.")
        second = submit(
            store.put_conditional, "cas.json", second_body, "application/json", if_match=first.etag
        )
        if second.outcome is not WriteOutcome.COMMITTED or not second.etag:
            raise Gate0CheckError("ETag compare-and-swap check failed.")
        stale = submit(
            store.put_conditional, "cas.json", stale_body, "application/json", if_match=first.etag
        )
        if stale.outcome is not WriteOutcome.REJECTED:
            raise Gate0CheckError("Stale ETag rejection check failed.")
        store.verify("cas.json", sha256_hex(second_body), len(second_body))
    except Gate0CheckError as exc:
        failure = str(exc)
    except Exception:
        # boto/botocore exceptions can contain request configuration; never surface them.
        failure = "The object-store check failed; service details were omitted."
    finally:
        if preflight_complete:
            # Remove only a key whose current body matches one of the bodies this run
            # submitted. This also leaves an object untouched if a concurrent writer
            # somehow populated our namespace after preflight.
            for key, expected_bodies in submitted_bodies.items():
                try:
                    current = store.read(key)
                    if current.body not in expected_bodies:
                        cleanup_failed.append(key)
                        continue
                    client.delete_object(Bucket=STAGING_BUCKET, Key=prefix + key)
                    store.stat(key)
                except ObjectNotFound:
                    # Confirmed absent now. That is clean unless a write with an unknown
                    # outcome could still land after this check exits.
                    if key in unsettled_keys:
                        cleanup_failed.append(key)
                    continue
                except Exception:
                    cleanup_failed.append(key)
                    continue
                cleanup_failed.append(key)  # still present after delete

    if cleanup_failed:
        keys = ", ".join(
            f"{STAGING_BUCKET}/{prefix}{key}" for key in sorted(set(cleanup_failed))
        )
        raise Gate0CheckError(
            f"{failure + ' ' if failure else ''}Cleanup could not be confirmed for "
            f"{keys}. Inspect only these test keys."
        )
    if failure:
        raise Gate0CheckError(failure)
    return prefix


def run_interactive_r2_gate0() -> int:
    """Prompt locally for staging credentials and run the guarded check."""
    import getpass
    import sys

    from bls_index.object_store import make_s3_client

    print(f"Opt-in real R2 check; fixed target bucket: {STAGING_BUCKET} (no bucket admin actions).")
    try:
        endpoint = validate_r2_endpoint(input("R2 endpoint URL: "))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    access_key_id = input("Access Key ID: ").strip()
    secret_access_key = getpass.getpass("Secret Access Key (hidden): ")
    if not access_key_id or not secret_access_key.strip():
        print("Access Key ID and Secret Access Key are required.", file=sys.stderr)
        return 2

    try:
        client = make_s3_client(endpoint, access_key_id, secret_access_key)
        prefix = run_r2_gate0(client)
    except Gate0CheckError as exc:
        print(f"R2 Gate0 check failed: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("R2 Gate0 setup failed; service details were omitted.", file=sys.stderr)
        return 1

    print(f"R2 Gate0 checks passed; temporary objects removed from {STAGING_BUCKET}/{prefix}.")
    return 0
