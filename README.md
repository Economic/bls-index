# bls_index

Builds and publishes a downloadable catalog of BLS time-series IDs and titles: one
compact Parquet file plus a `latest.json` manifest. [`design.md`](design.md) is the
contract and [`plans/2026-10-13-simplification-implementation.md`](plans/2026-10-13-simplification-implementation.md)
is the implementation plan.

**Status:** all 33 programs build, and publishing through GitHub Releases is written
and tested offline (plan Phase 2). Nothing is published yet.

## Build and test

One command, used locally and in CI:

```sh
./scripts/check.sh            # uv sync --frozen, then the offline pytest suite
./scripts/check.sh -k builder # extra arguments go to pytest
```

The suite needs no network access and no credentials. It starts a local HTTP fixture
server on `127.0.0.1`.

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

## Publishing

The `daily` GitHub Actions workflow builds the catalog every day. When the latest
release is at least 6 days old, it also publishes the catalog and its `latest.json`
manifest as a GitHub Release, through `bls-index manifest`, `bls-index publish-due` and
`scripts/publish.sh`. The release stays a draft until GitHub's SHA-256 digests of both
files match the local files. A manual run can choose `publish: force`, `test` (a
prerelease that never becomes "latest"), or `none` (build only), and can build a subset
of programs, which never publishes. Runs report to a healthchecks.io monitor through
the `HEALTHCHECKS_URL` secret.

## Searching the catalog from R

`examples/find_bls.R` is a reference client for `epidatatools::find_bls()`:

```r
source("examples/find_bls.R")
find_bls("unemployment rate", survey = c("ln", "la"), seasonality = "SA")
```

It needs `arrow`, `dplyr`, `jsonlite`, `openssl`, `rlang`, `SnowballC` and `tibble`.
Until a catalog is published, point it at a local build's manifest with
`options(bls_index.manifest_url = "file:///path/to/latest.json")`.
`examples/check_find_bls.R` checks its search rules offline against a catalog from
`scripts/fixture_catalog.py`. R code here uses `<-` for assignment.

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
  manifest.py            latest.json and the weekly publish decision
examples/
  find_bls.R             reference R client; check_find_bls.R checks it offline
scripts/
  check.sh               the build and test command
  golden.py              compare a refactor's rows with a saved run
  fixture_catalog.py     small catalog and manifest from the test fixtures
  publish.sh             publish a built catalog as a GitHub Release
tests/
  harness/               controlled HTTP source serving scripted replies
  fixtures/              real sample rows for every program; two_program/ is served over HTTP
docs/                    schema, synthesized-title contracts, evidence
```

Raw BLS files and credentials are never committed.
