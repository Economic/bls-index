# bls_index design

Rewritten 2026-10-13 to a smaller scope. The previous version (journaled manifest writes,
per-program fallback, scope releases, rollback records, host-move rehearsals) is in git
history at `3513fb6`. The reasons for the change are in
[`plans/2026-10-13-simplification-review.md`](plans/2026-10-13-simplification-review.md).

## Purpose

The BLS Data Finder, the only tool for searching BLS series by name, is down, and
`epidatatools::find_bls()` depended on it. This project publishes a replacement: a
downloadable catalog of BLS series IDs and titles, rebuilt daily from the official flat
files at `https://download.bls.gov/pub/time.series/`. A future `find_bls()` downloads the
file once, caches it, and searches locally.

"Current" means present in the latest successfully ingested `.series` files. Still-listed
frozen series belong in the catalog. The catalog does not judge whether a series is live.

## Non-goals

- No hosted search API, browser UI, or remote query (SQLite over HTTP, DuckDB range reads).
- No series liveness status. `end_year` and `end_period` are source metadata only.
- No mixed catalogs. A published catalog is always built from one run in which every
  in-scope program succeeded.
- No runtime scope changes. Scope is code, changed by pull request.
- No automated rollback or cleanup logic. Recovery is a manual operator step.
- No historical archive beyond a short retention window.
- No `epidatatools` changes in this repository. Client behavior is described here only
  as far as it constrains publication.

## Scope

v1 publishes exactly 33 programs, defined in `src/bls_index/scope.py`:

- 30 programs with native titles: `ap`, `bd`, `ce`, `ci`, `cm`, `cu`, `cw`, `cx`, `ei`,
  `ep`, `fm`, `ip`, `is`, `kv`, `la`, `le`, `ln`, `lu`, `mp`, `nb`, `nd`, `oe`, `or`,
  `pc`, `su`, `tu`, `wd`, `wm`, `wp`, `ws`.
- 3 programs with synthesized titles: `sm`, `jt`, `pr`.

Scope never comes from BLS directory listings or from a failed or missing source. The
remaining 21 programs (frozen twins, injuries and illnesses, standalone frozen programs)
and the excluded `nw` and case-characteristics programs are future work. Each addition
is a pull request that adds a builder, tests, and the code to `scope.py`; the next daily
run publishes it if all programs pass.

## Catalog

One zstd-compressed Parquet file, one row per series. Column definitions, types and
normalization rules are in [`docs/schema-v1.md`](docs/schema-v1.md); machine-checkable
constraints are in the repository-root [`data-dict.yaml`](data-dict.yaml).

| Column | Type | Notes |
|---|---|---|
| `program` | string | BLS program code from scope, never inferred from the ID |
| `series_id` | string | Trimmed; unique across the catalog; compared exactly as spelled |
| `series_title` | string | Native title preserved as published, or synthesized from lookups |
| `title_source` | string | `native` or `synthesized` |
| `seasonal` | string | `SA`, `NSA`, or `unknown` |
| `begin_year`, `end_year` | int32, nullable | Four-digit source years |
| `end_period` | string, nullable | Source period code, such as `M08` |

Titles need not be unique. Schema version 1 is separate from the data-dict `$version`.
`survey_name` and `begin_period` are deferred.

## Build

Each run builds all 33 programs from fresh downloads into a private run directory.

**Fetching.** Fetch each input once over HTTPS, with:

- a descriptive, contactable User-Agent from the `BLS_INDEX_USER_AGENT` secret (BLS
  returns 403 for agents containing "github")
- at most one request start per second
- timeouts, and bounded retries with backoff for 429, 5xx and transport errors
- a check that the body length matches `Content-Length`

Never use `HEAD`, `ETag` or `Last-Modified` to skip a download. Record each input's URL,
byte count and SHA-256 in the run report.

**Native parsers.** Read the header and find the needed columns by name: `series_id`,
`series_title`, `seasonal` (if present), `begin_year`, `end_year`, and `end_period`. Fail
the program if:

- a needed column is missing
- any row has a different field count from the header
- the file is not valid UTF-8, or has no data rows
- any ID is blank, duplicated, or lacks the program's prefix
- any title is blank
- any year is present but not four digits

Map seasonal codes `S` to `SA` and `U` to `NSA`. Map anything else, or a missing column,
to `unknown`, and log unexpected codes. Extra or reordered columns do not fail a program.

**Synthesized titles** (`sm`, `jt`, `pr`). Join `.series` to its lookup files and format a
reviewed title template. Fail the program on:

- a lookup key that matches zero rows, or more than one row
- a missing label
- an output row count that differs from the `.series` row count

The templates and lookup files are documented in
[`docs/synthesized-source-contracts.md`](docs/synthesized-source-contracts.md).

**Combined candidate.** Concatenate all 33 programs and check:

- the exact scope
- the canonical schema
- global `series_id` uniqueness

Then run the pinned `data-dict` `validate-spec`, `validate-meta` and `validate-data` on
the written Parquet. Row counts are kept in the run report as diagnostics. A change in
row count alone is not a failure.

If any program or any combined check fails, the run fails and publishes nothing.

## Publication

The storage is Cloudflare R2, accessed through its S3 API. Gate 0 (2026-10-12) verified
`If-None-Match: *` and `If-Match` conditional writes on R2.

Public objects live under `/v1/` in the public bucket:

- `v1/catalog/bls_index-<sha256>.parquet`: immutable, content-addressed catalog
- `v1/manifests/<build_id>.json`: immutable copy of each published manifest
- `v1/latest.json`: the current manifest, the only object that is ever replaced

A run publishes in this order:

1. Read `latest.json` and remember its ETag, or confirm that it does not exist.
2. Upload the catalog. Read it back and verify its SHA-256 and size.
3. Upload the manifest copy to `v1/manifests/<build_id>.json`.
4. Write `latest.json` conditionally, with `If-Match: <etag>`. For the first
   publication, use `If-None-Match: *`.
5. Handle the response:
   - **Success:** done.
   - **412 (another write got there first):** fail the run.
   - **Timeout or unclear response:** re-read `latest.json`. If it contains this run's
     `build_id`, the write committed. Otherwise retry once with the same condition, then
     fail.

`latest.json` must never be written before the catalog it references has passed
read-back verification. That is the one ordering rule.

Every outcome is safe. A write that lands late still points at a verified catalog, and
the conditional header stops it from replacing a newer manifest. A failed run leaves
yesterday's manifest in place.

**Manifest fields:**

- `manifest_version`: 1
- `schema_version`: 1
- `build_id`: unique per run
- `built_at`: UTC time the run started downloading
- `published_at`
- `catalog`:
  - `path`, relative to the manifest
  - `sha256`
  - `bytes`
  - `rows`
- `programs`: a list of
  - `program`
  - `rows`
  - `inputs`, each with `file`, `bytes` and `sha256`

Object paths are relative to the manifest's own URL. A path contains only `/`-separated,
nonempty segments of `A-Z a-z 0-9 . _ -`, and no segment may be `.` or `..`. Builds and
clients reject any other form. The manifest names no host.

**Retention.** An R2 lifecycle rule deletes objects under `v1/catalog/` and
`v1/manifests/` 90 days after upload. `latest.json` is not covered by the rule. 90 days
is a starting point; shorten it once real rollback needs are known. Daily failure alerts
make an unnoticed outage longer than the window implausible. That remaining risk is
listed under accepted risks.

**Manual recovery.** To roll back, verify an older `v1/manifests/<build_id>.json` and the
catalog it names, then copy it to `latest.json` with `If-Match`. The runbook documents
this step.

## Operations

- **Daily workflow.** A GitHub Actions workflow on a standard Linux runner, scheduled
  daily and dispatchable by hand. It runs build, then publish. It is in concurrency group
  `bls-index-publish` with `cancel-in-progress: false`. A pending run may be replaced by
  a newer pending run, which is fine.
- **Alerts.** One healthchecks.io check (free tier) handles both kinds of alert, by
  email to the maintainer:
  - **Failed runs.** The workflow pings `/start` when it begins, the success URL after
    publishing, and `/fail` from an `if: failure()` step. An explicit failure alerts
    within minutes.
  - **Missed runs.** With a 1-day period and a 1-day grace time, a missing success ping
    alerts within about 48 hours. That covers runs that never start, including GitHub
    disabling the schedule in an inactive repository.

  GitHub's own failed-run emails are a bonus, not a dependency.
- **Artifacts.** GitHub Actions artifacts hold diagnostics only: the run report and logs.
  R2 holds everything durable.
- **Credentials.** R2 credentials are scoped to the publication bucket and stored as
  repository secrets. Workflows never hold `contents: write`.
- **Staging.** The `bls-index-staging` bucket, on hostname
  `bls-index-staging.benzipperer.org`, exercises the full workflow before launch.

## Serving and discovery

- **Storage.** The R2 Standard bucket `bls-index`, behind the Cloudflare custom domain
  `bls-index.benzipperer.org`, with the public `r2.dev` URL disabled. Reads need no key
  and no JavaScript challenge, and must work from `curl` and R. The data host can move:
  clients find it through the discovery pointer.
- **Caching.** A long TTL for `/v1/catalog/*.parquet` and `/v1/manifests/*`, and a short
  TTL for `latest.json`. No CAPTCHA or managed challenge. Add a path-scoped rate-limit
  rule only after measuring real traffic. Configure usage and budget alerts, which are
  not hard caps.
- **Discovery pointer.** `https://economic.github.io/bls-index/endpoint.json`, served by
  GitHub Pages from a dedicated `pages/` folder, contains `{"schema_version": 1,
  "manifest_url": "https://<data host>/v1/latest.json"}`. It changes only through a
  reviewed commit. Publish it only after the first public `latest.json` exists. Moving
  the data host means attaching a new domain to the same bucket and updating the
  pointer. The relative manifest paths need no rewrite.

**Client expectations,** to be specified fully in the client's own repository:

- Start from the pointer.
- Fetch the manifest at most about once per session, revalidating with ETags.
- Verify the catalog SHA-256, and cache it by checksum.
- Accept only `https` URLs.
- Treat the catalog as stale when `built_at` is more than 48 hours old.
- Send a User-Agent that names the client.

## Accepted risks

These are deliberate. Reviews should not report them as defects.

1. **One broken program blocks every update.** All 33 programs then stop updating until
   the problem is fixed. Clients see `built_at` age.
2. **Single download.** Each file is downloaded once. A file that changes during the
   download and still passes every check can be published, and the next run corrects it.
3. **Valid but incomplete sources are published.** A structurally valid but incomplete
   source is published, because row-count changes are diagnostics, not failures.
4. **Native parsers check only the columns the catalog uses.** BLS's internal
   consistency between IDs and their dimension columns is not checked.
5. **Unclear write outcomes can mislead alerts.** A run whose manifest write outcome
   stays unclear may report failure even though it published. The next run reads
   whatever is current.
6. **Retention is a fixed window.** An outage longer than the retention window
   would expire the catalog that `latest.json` points to.
7. **Orphaned uploads.** Uploaded catalogs that no manifest references remain publicly
   fetchable until they expire.

## Decisions

- **Python, uv, polars,** with a pinned `data-dict-yaml` (2026-10-06).
- **Discovery** through the GitHub Pages pointer, with relative manifest paths
  (2026-10-07).
- **R2 conditional writes** verified in Gate 0 (2026-10-12).
- **Diagnostic row counts only:** no thresholds or warning state (2026-10-13).
- **Operations** (2026-10-13):
  - Two buckets: `bls-index` (production) and `bls-index-staging` (staging), both
    public through their custom domains.
  - healthchecks.io for alerts.
  - 90-day retention as a starting point.
- **Simplification** (2026-10-13), covering:
  - complete-only publication
  - scope in code
  - no journal
  - single download
  - name-based native parsing
  - lifecycle retention
  - manual recovery

## Done when

1. `./scripts/check.sh` passes offline, locally and in CI.
2. The daily workflow builds all 33 programs, publishes to production, and has run
   successfully for 7 consecutive days.
3. A failed run leaves the previous manifest in place and alerts. The dead-man's-switch
   monitor alerts when no successful publish happens within 48 hours.
4. The pointer resolves to the production manifest. `curl` and R download the catalog
   from an outside machine without credentials, and the checksum matches. Cache headers
   are as configured.
5. The runbook covers credentials, a manual rerun, rollback, adding a program, alerts,
   and costs.
