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

The suite needs no network access to BLS or object storage and no credentials. It starts a
local moto S3 server and local HTTP fixture servers on `127.0.0.1`.

### Optional real R2 Gate 0 check

Only run this on request, from a developer machine, after creating the **private** staging
bucket `bls-index-staging`. This check is separate from the offline suite:

```sh
uv run bls-index r2-gate0
```

Enter the Cloudflare account endpoint (`https://<account-id>.r2.cloudflarestorage.com`),
then the Access Key ID and Secret Access Key when prompted; the secret prompt is hidden.
Use an R2 token scoped only to `bls-index-staging`, with object read, write, and delete
permissions (GetObject, HeadObject, PutObject, DeleteObject). The check does not create or
delete buckets, list objects, alter bucket settings, or access any other bucket. It uses a
fresh `gate0/<random-id>/` namespace and removes only its own matching test objects, including
on failure; if cleanup cannot be confirmed, it prints the exact keys to inspect. The check
covers create-if-absent and duplicate rejection, ETag compare-and-swap and stale rejection,
confirmed absence, and SHA-256 read-back. It does not test concurrency or broader deployment
behavior. Do not pass credentials on the command line or save them in environment/config
files. `./scripts/check.sh` remains offline and never requests credentials.

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
uv run bls-index dry-build --programs initial --workdir ./benchmarks
uv run bls-index dry-build --programs ap,pr --workdir ./benchmarks  # local/offline fixture source via --base-url
uv run bls-index runner-info                   # CPU, memory, disk of this machine
```

The probe downloads each program's inputs in full, downloads them again, and compares
SHA-256 (it never uses HEAD, ETag, or Last-Modified to skip a download). It records
response metadata, sizes, checksums and file layouts, and with `--parse-check` measures
polars parse time and peak memory. Raw downloads go to a temporary directory and are
deleted. The `source-probe` GitHub Actions workflow runs the same probe on a clean
runner; it reads the User-Agent from the repository secret `BLS_INDEX_USER_AGENT`.

### Local dry builds and measurements

`dry-build` runs one requested program at a time. It downloads and rechecks verified
inputs using the same fetcher, builds local content-addressed per-program Parquet bundles,
then reloads those bundles and validates a combined candidate with the pinned
`data-dict` executable only after every requested program succeeds. It defaults to the
fixed initial 33-program scope; `--programs` accepts an explicit unique subset. Each
invocation creates a new `dry-build-<UTC-time>-<random-id>` directory under required
`--workdir`; it does not replace prior runs. The run includes `report.json`, raw verified
source inputs, per-program artifacts, and `combined/bls_index.parquet` only on success.
Failed and incomplete runs write a diagnostic report and do not expose a combined
candidate. `report.json` is checkpointed at run start and after each program; a recoverable
failure records the failed stage. A hard process kill or unavailable/full disk cannot be
caught or reported reliably: in those cases only the last successfully written checkpoint
may remain, and no stronger recovery guarantee is made. The repository includes a manually
dispatched GitHub Actions workflow that runs the dry build and retains diagnostic JSON only;
it does not publish or upload source inputs or Parquet artifacts.

For a controlled offline run, use the local fixture HTTP source from the test harness or
serve a compatible fixture tree and pass its URL with `--base-url`; the default base URL
is the live BLS source. A descriptive contactable `BLS_INDEX_USER_AGENT` is required in
either case. Request pacing defaults to one second and may be lowered only for loopback
fixture servers. Fetch attempts are bounded by `--max-request-attempts` and
`--max-input-set-attempts`.

The JSON report records requested scope and per-input sizes/SHA-256, per-program
download/build durations, row counts and bundle checksums, combined artifact size/checksum,
pinned dictionary validation durations, combined-Parquet load time, representative
in-memory search query durations and result counts, source total bytes, runtime/platform/CPU/
revision, peak RSS, filesystem capacity/output bytes, and sampled peak run-directory bytes
and filesystem use/free space. Sampling runs every 0.25 seconds and includes temporary
combined-candidate staging and downloads, but short-lived peaks between samples may be missed;
these are sampled peaks, not absolute guaranteed maxima. A full initial-scope run fails validation
and exposes no combined candidate if either representative query has zero results; explicit
subsets may return zero. Search examples are unemployment
in `ln` with `NSA` seasonality and registered nurses in `oe` with `NSA` seasonality; each
query reports count and elapsed time separately from the combined-file load. Timings are
observations, not estimates or acceptance thresholds. Peak RSS records both `getrusage(RUSAGE_SELF)` and
`getrusage(RUSAGE_CHILDREN)`, including terminated `data-dict` child processes. The child
value is the maximum child-process peak, not a concurrent aggregate; both values use the
same platform-specific source unit (KiB except bytes on macOS) and include normalized
bytes. The self value covers this Python process's prior lifetime peak. `data-dict` timings
are wall-clock subprocess times; query timings exclude the initial
combined-Parquet read. Disk free space is an instantaneous capacity reading, not a
reservation. The default `initial` run may be expensive and needs adequate space for raw
inputs, per-program outputs, and the combined output. A successful full-33 intended-runner
measurement is recorded in [the Phase 1 benchmark](docs/evidence/2026-10-13-phase1-benchmark.md).
It demonstrates single-run feasibility, not historical reliability or justified count-change
thresholds; the evidence document lists remaining Gate 1 checks.

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
