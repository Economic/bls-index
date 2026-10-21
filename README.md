# bls_index

A downloadable, searchable catalog of BLS time-series IDs and titles, rebuilt from the
official flat files at <https://download.bls.gov/pub/time.series/>. It replaces the BLS
Data Finder, which `epidatatools::find_bls()` relied on and which is no longer
available.

The catalog is one Parquet file (about 33 MB, 8.3 million series in 33 BLS programs)
plus a small `latest.json` manifest, published as GitHub Releases of this repository.
[`design.md`](design.md) is the contract;
[`plans/2026-10-21-next-steps.md`](plans/2026-10-21-next-steps.md) has the status and
next steps. Agents start with [`AGENTS.md`](AGENTS.md).

**Status:** building and publishing work, and test releases passed on GitHub. The first
catalog release is due from the scheduled run on 2026-10-21.

## Using the catalog

Once published, the latest catalog is always at:

- manifest: <https://github.com/Economic/bls-index/releases/latest/download/latest.json>
- catalog: the `catalog.url` named in that manifest

Each row is one series: `program`, `survey_name`, `survey_aliases`, `series_id`,
`series_title`, `title_source`, `seasonal`, `begin_year`, `end_year` and `end_period`.
See [`docs/schema-v1.md`](docs/schema-v1.md). Survey names and aliases, such as "CPI"
or "JOLTS", are listed in [`docs/survey-names.md`](docs/survey-names.md).

### From R

`examples/find_bls.R` is a reference client for `epidatatools::find_bls()`:

```r
source("examples/find_bls.R")
find_bls("unemployment rate", survey = c("ln", "la"), seasonality = "SA")
find_bls("all items", survey = "cu", titles_only = TRUE)
```

It downloads the catalog at most once a week into `tools::R_user_dir("epidatatools",
"cache")`, verifies its checksum, and searches the cached file in place, in about a
second. Every search word must match (stemmed, so "nurses" finds "nursing"). Results
are sorted with the most matched words first, then shortest title, and cut at
`limit = 1000` with a count of matches by survey. The design's "Clients" section has
the full rules.

It needs `arrow`, `dplyr`, `jsonlite`, `openssl`, `rlang`, `SnowballC` and `tibble`.
Until a catalog is published, point it at a manifest with
`options(bls_index.manifest_url = ...)`, either a test release's `latest.json` or a
local file. `examples/check_find_bls.R` checks its search rules offline against a
catalog from `scripts/fixture_catalog.py`. R code here uses `<-` for assignment.

## Building the catalog

```sh
./scripts/check.sh            # uv sync --frozen, then the offline pytest suite
./scripts/check.sh -k builder # extra arguments go to pytest
```

The suite needs no network access and no credentials. Toolchain: Python 3.13 and
dependencies pinned in `pyproject.toml` and `uv.lock`, including the `data-dict`
validator. Install [uv](https://docs.astral.sh/uv/) 0.10.3 or later; CI pins 0.10.3.

`download.bls.gov` rejects anonymous clients, so set a descriptive User-Agent with
contact details. It must not contain "github", which BLS answers with 403.

```sh
export BLS_INDEX_USER_AGENT='bls_index catalog builder <you@example.org>'
uv run bls-index build --workdir ./runs                    # all 33 programs
uv run bls-index build --programs ap,pr --workdir ./runs   # a subset
uv run pytest -m live                                      # small real-BLS smoke test
```

Each run creates `runs/build-<UTC time>-<id>/` with the downloaded sources,
`report.json`, and, only if every program and the combined checks pass,
`bls_index.parquet`. The report lists each program's source files (bytes and SHA-256),
row count, timings and warnings. A full build takes about 5 minutes on a GitHub runner.
Requests start at most once per second, because BLS blocks faster robots.

`scripts/golden.py RUN_DIR` rebuilds every program from a saved run's downloads and
compares the rows with that run's output, to check that a code change leaves the
catalog unchanged.

## Publishing

The `daily` GitHub Actions workflow builds the catalog every day. When the latest
release is at least 6 days old, it also publishes the catalog and `latest.json` as a
release (`bls-index manifest`, `bls-index publish-due`, `scripts/publish.sh`):

- The release stays a draft until GitHub's SHA-256 digests of both files match the
  local files.
- Only the publish job can write to the repository, and it never handles downloaded
  BLS data.
- The newest 12 releases are kept.

A manual run can choose `publish: force`, `test` (a prerelease that never becomes
"latest"), or `none` (build only). It can also build a subset of programs, which never
publishes. Runs report to a healthchecks.io monitor through the `HEALTHCHECKS_URL`
secret, which emails the maintainer when a run fails or does not happen.

## Layout

```
src/bls_index/
  scope.py               the 33 programs, lookup files, survey names and aliases
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
  publish.sh             publish a built catalog as a GitHub Release
  golden.py              compare a code change's rows with a saved run
  fixture_catalog.py     small catalog and manifest from the test fixtures
tests/
  harness/               a scripted local HTTP server and a fake `gh`
  fixtures/              real sample rows for every program
docs/                    schema, survey names, synthesized titles, evidence
```

Raw BLS files and credentials are never committed.

## Acknowledgments

Two projects already make BLS series easier to find, and informed this one:

- **[BLS Series Lookup](https://prestonmui.github.io/bls-series-lookup/)** by Preston
  Mui ([source](https://github.com/PrestonMui/bls-series-lookup)) is a browser search
  of BLS series descriptions and IDs across 11 programs, with filters by program and
  seasonal adjustment and CSV export.
- **[DBnomics](https://db.nomics.world/BLS)** ingests the BLS flat files, keeps BLS
  series IDs, and offers full-text search through a web interface, an API, and R, Python
  and Stata clients.

`bls_index` differs mainly in scope and form: it covers every series in 33 BLS programs,
including OEWS, refreshes weekly from the flat files, and publishes a single file for
offline search from R.
