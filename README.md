# bls_index

Builds and publishes a downloadable catalog of BLS time-series IDs and titles: one
compact Parquet file plus a `latest.json` manifest. [`design.md`](design.md) is the
contract and [`docs/plans/implementation-plan-v1.md`](docs/plans/implementation-plan-v1.md)
is the implementation plan.

**Status:** Phase 0 (build toolchain and controlled integration harness). Nothing is
published yet, and no code here writes to a public bucket.

## Build and test

One command, used locally and in CI:

```sh
./scripts/check.sh            # uv sync --frozen, then the offline pytest suite
./scripts/check.sh -k object  # extra arguments go to pytest
```

The suite needs no network access to BLS and no credentials. It starts a local moto S3
server and local HTTP fixture servers on `127.0.0.1`.

Toolchain: Python 3.13 (`.python-version`) and dependencies pinned in `pyproject.toml`
and `uv.lock`, including the `data-dict` validator (`data-dict-yaml` on PyPI). Install
[uv](https://docs.astral.sh/uv/) 0.10.3 or later; CI pins 0.10.3.

## Talking to BLS

`download.bls.gov` rejects anonymous clients. Every real request needs a descriptive
User-Agent with contact details, set via the environment:

```sh
export BLS_INDEX_USER_AGENT='bls_index catalog builder (+https://example.org/contact)'
uv run pytest -m live                          # small real-BLS smoke test (opt-in)
uv run bls-index probe --programs oe,ap,pr --parse-check --out probe.json
uv run bls-index probe --programs initial --out probe.json   # all 33 programs
uv run bls-index runner-info                   # CPU, memory, disk of this machine
```

The probe downloads each program's inputs in full, downloads them again, and compares
SHA-256 (it never uses HEAD, ETag, or Last-Modified to skip a download). It records
response metadata, sizes, checksums and file layouts, and with `--parse-check` measures
polars parse time and peak memory. Raw downloads go to a temporary directory and are
deleted. The `source-probe` GitHub Actions workflow runs the same probe on a clean
runner; it reads the User-Agent from the repository secret `BLS_INDEX_USER_AGENT`.

Two BLS constraints, observed 2026-10-07: `download.bls.gov` returns 403 for any
User-Agent containing "github", and BLS blocks robots that request "multiple times per
second". The fetcher rejects such agents and spaces request starts at least one second
apart (`--min-request-interval`).

## Layout

```
src/bls_index/
  scope.py          fixed initial 33 programs and sm/jt/pr lookup files
  clock.py          injectable UTC clock
  events.py         ordered event log (exported as JSON Lines)
  http_source.py    BLS fetcher: retries, bounded concurrency, input-set recheck
  object_store.py   S3/R2 adapter: create-if-absent, compare-and-swap, read-back verify
  notifier.py       alert interface (destination not yet chosen)
  probe.py, cli.py  source inventory probe and `bls-index` command
tests/
  harness/          controlled HTTP source, moto + fault proxy, fake clock and notifier,
                    event-order assertions
  fixtures/         tiny two-program fixture (ap native, pr synthesized) from real rows
docs/evidence/      measurements and checks recorded for the plan's gates
```

Raw BLS files and credentials are never committed.
