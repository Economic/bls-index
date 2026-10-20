# bls_index

Builds and publishes a downloadable catalog of BLS time-series IDs and titles: one
compact Parquet file plus a `latest.json` manifest. [`design.md`](design.md) is the
contract and [`plans/2026-10-13-simplification-implementation.md`](plans/2026-10-13-simplification-implementation.md)
is the implementation plan.

**Status:** all 33 programs build locally (plan Phase 1). Publishing is not built yet;
nothing is published and no code here writes to a public bucket.

## Build and test

One command, used locally and in CI:

```sh
./scripts/check.sh            # uv sync --frozen, then the offline pytest suite
./scripts/check.sh -k builder # extra arguments go to pytest
```

The suite needs no network access and no credentials. It starts a local moto S3 server
and a local HTTP fixture server on `127.0.0.1`.

Toolchain: Python 3.13 (`.python-version`) and dependencies pinned in `pyproject.toml`
and `uv.lock`, including the `data-dict` validator (`data-dict-yaml` on PyPI). Install
[uv](https://docs.astral.sh/uv/) 0.10.3 or later; CI pins 0.10.3.

## Building the catalog

`download.bls.gov` rejects anonymous clients, so set a descriptive User-Agent with
contact details. It must not contain "github", which BLS answers with 403.

```sh
export BLS_INDEX_USER_AGENT='bls_index catalog builder <you@example.org>'
uv run bls-index build --workdir ./runs                    # all 33 programs
uv run bls-index build --programs ap,pr --workdir ./runs   # a subset
uv run pytest -m live                                      # small real-BLS smoke test
```

Each run creates `runs/build-<UTC time>-<id>/` containing the downloaded sources,
`report.json`, and, only if every program and the combined checks pass,
`bls_index.parquet`. The report lists each program's source files (bytes and SHA-256),
row count, timings, and any warnings, plus the catalog's size and SHA-256. The build
stops at the first failed program.

Requests start at most once per second, and BLS blocks faster robots. `--base-url` with a
loopback address and `--min-request-interval 0` run against a local copy instead.

The manual `build` GitHub Actions workflow runs the same command on a clean runner and
uploads only the report and resource usage.

`scripts/golden.py RUN_DIR` rebuilds every program from a saved run's downloads and
compares the rows with that run's output. It checks that a refactor did not change the
catalog.

## Layout

```
src/bls_index/
  scope.py               fixed 33-program scope and sm/jt/pr lookup files
  http_source.py         BLS fetcher: pacing, retries, Content-Length check
  schema.py              catalog schema v1, tab-separated reader, shared row checks
  builders.py            native titles and sm/jt/pr title synthesis
  combined_candidate.py  combined checks and the pinned data-dict validation
  build.py, cli.py       the build run, its report, and the `bls-index` command
  object_store.py        S3/R2 adapter for the publish step (Phase 2)
tests/
  harness/               controlled HTTP source, moto server and fault proxy
  fixtures/              real sample rows for every program; two_program/ is served over HTTP
docs/                    schema, synthesized-title contracts, evidence and history
```

Raw BLS files and credentials are never committed.
