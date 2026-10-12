"""Offline checks for the explicitly opted-in R2 Gate 0 runner."""

from __future__ import annotations

import pytest

from bls_index import object_store
from bls_index.cli import main
from bls_index import r2_gate0
from bls_index.r2_gate0 import (
    Gate0CheckError,
    STAGING_BUCKET,
    run_r2_gate0,
    validate_r2_endpoint,
)


@pytest.fixture

def staging_bucket(backdoor):
    backdoor.create_bucket(Bucket=STAGING_BUCKET)
    yield
    backdoor.delete_bucket(Bucket=STAGING_BUCKET)


def test_gate0_runner_uses_production_adapter_and_cleans_its_prefix(backdoor, staging_bucket):
    prefix = run_r2_gate0(backdoor, run_id="a" * 32)

    assert prefix == "gate0/" + "a" * 32 + "/"
    for key in ("immutable.bin", "cas.json", "confirmed-absent.json"):
        with pytest.raises(backdoor.exceptions.NoSuchKey):
            backdoor.get_object(Bucket=STAGING_BUCKET, Key=prefix + key)


def test_gate0_runner_refuses_preexisting_key_before_any_writes(backdoor, staging_bucket):
    prefix = "gate0/" + "b" * 32 + "/"
    backdoor.put_object(Bucket=STAGING_BUCKET, Key=prefix + "cas.json", Body=b"untouched")

    with pytest.raises(Gate0CheckError, match="already exists"):
        run_r2_gate0(backdoor, run_id="b" * 32)

    assert backdoor.get_object(Bucket=STAGING_BUCKET, Key=prefix + "cas.json")["Body"].read() == b"untouched"
    backdoor.delete_object(Bucket=STAGING_BUCKET, Key=prefix + "cas.json")
    with pytest.raises(backdoor.exceptions.NoSuchKey):
        backdoor.get_object(Bucket=STAGING_BUCKET, Key=prefix + "immutable.bin")


def test_gate0_runner_cleans_own_object_after_check_failure(backdoor, staging_bucket, monkeypatch):
    unrelated_key = "operator-data/leave-me-alone"
    backdoor.put_object(Bucket=STAGING_BUCKET, Key=unrelated_key, Body=b"untouched")
    original_verify = r2_gate0.S3ObjectStore.verify

    def fail_verify(self, key, sha256, size=None):
        if key == "immutable.bin":
            raise object_store.ChecksumMismatch("injected test failure")
        return original_verify(self, key, sha256, size)

    monkeypatch.setattr(r2_gate0.S3ObjectStore, "verify", fail_verify)
    prefix = "gate0/" + "d" * 32 + "/"
    with pytest.raises(Gate0CheckError, match="service details were omitted"):
        run_r2_gate0(backdoor, run_id="d" * 32)

    with pytest.raises(backdoor.exceptions.NoSuchKey):
        backdoor.get_object(Bucket=STAGING_BUCKET, Key=prefix + "immutable.bin")
    assert backdoor.get_object(Bucket=STAGING_BUCKET, Key=unrelated_key)["Body"].read() == b"untouched"
    backdoor.delete_object(Bucket=STAGING_BUCKET, Key=unrelated_key)


def test_gate0_endpoint_requires_exact_cloudflare_https_account_endpoint():
    assert validate_r2_endpoint(" https://abc123.r2.cloudflarestorage.com/ ") == (
        "https://abc123.r2.cloudflarestorage.com"
    )
    for endpoint in (
        "http://abc123.r2.cloudflarestorage.com",
        "https://example.com",
        "https://abc123.r2.cloudflarestorage.com/other",
        "https://access:secret@abc123.r2.cloudflarestorage.com",
        "https://abc123.r2.cloudflarestorage.com?secret=hidden",
    ):
        with pytest.raises(ValueError):
            validate_r2_endpoint(endpoint)


def test_invalid_endpoint_stops_before_credentials_or_client(monkeypatch, capsys):
    asked: list[str] = []

    def prompt(label: str) -> str:
        asked.append(label)
        return "http://not-r2.example"

    monkeypatch.setattr("builtins.input", prompt)
    monkeypatch.setattr(
        object_store,
        "make_s3_client",
        lambda *args, **kwargs: pytest.fail("client must not be created for invalid endpoint"),
    )

    assert main(["r2-gate0"]) == 2
    assert asked == ["R2 endpoint URL: "]
    assert "HTTPS Cloudflare R2" in capsys.readouterr().err


def test_interactive_command_hides_secret_and_does_not_report_it(monkeypatch, capsys):
    secret = "never-print-this-secret"
    inputs = iter(("https://abc123.r2.cloudflarestorage.com", "staging-key-id"))
    monkeypatch.setattr("builtins.input", lambda _label: next(inputs))
    monkeypatch.setattr("getpass.getpass", lambda _label: secret)
    monkeypatch.setattr(object_store, "make_s3_client", lambda *args: object())
    monkeypatch.setattr(
        "bls_index.r2_gate0.run_r2_gate0", lambda _client: "gate0/" + "c" * 32 + "/"
    )

    assert main(["r2-gate0"]) == 0
    output = capsys.readouterr()
    assert secret not in output.out
    assert secret not in output.err
    assert "temporary objects removed" in output.out


def test_interactive_command_redacts_service_exception(monkeypatch, capsys):
    secret = "never-print-this-secret"
    inputs = iter(("https://abc123.r2.cloudflarestorage.com", "staging-key-id"))
    monkeypatch.setattr("builtins.input", lambda _label: next(inputs))
    monkeypatch.setattr("getpass.getpass", lambda _label: secret)
    monkeypatch.setattr(object_store, "make_s3_client", lambda *args: object())

    def fail(_client):
        raise RuntimeError(f"client configuration leaked {secret}")

    monkeypatch.setattr("bls_index.r2_gate0.run_r2_gate0", fail)

    assert main(["r2-gate0"]) == 1
    output = capsys.readouterr()
    assert secret not in output.out
    assert secret not in output.err
    assert "service details were omitted" in output.err
