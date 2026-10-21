# bls_index design

Rewritten 2026-10-13 to a smaller scope, and revised 2026-10-20 to publish through GitHub
Releases. The original version (journaled manifest writes, per-program fallback, scope
releases, rollback records, host-move rehearsals) is in git history at `3513fb6`; the
R2-based version is at `428a286`. The reasons are in
[`plans/2026-10-13-simplification-review.md`](plans/2026-10-13-simplification-review.md)
and the 2026-10-20 decisions below.

## Purpose

The BLS Data Finder, the only tool for searching BLS series by name, is down, and
`epidatatools::find_bls()` depended on it. This project publishes a replacement: a
downloadable catalog of BLS series IDs and titles, built daily from the official flat
files at `https://download.bls.gov/pub/time.series/` and published weekly. A future
`find_bls()` downloads the catalog at most once a week, caches it, and searches it
locally.

"Current" means present in the latest successfully ingested `.series` files. Still-listed
frozen series belong in the catalog. The catalog does not judge whether a series is live.

## Non-goals

- No hosted search API, browser UI, or remote query service.
- No series liveness status. `end_year` and `end_period` are source metadata only.
- No mixed catalogs. A published catalog is always built from one run in which every
  in-scope program succeeded.
- No runtime scope changes. Scope is code, changed by pull request.
- No change history between catalogs, such as lists of added or removed series
  (considered and dropped 2026-10-20). Old releases keep old catalogs for a while.
- No automated rollback. Retention deletes releases beyond the newest 12.
- No discovery pointer. Clients use the GitHub Releases URL directly.
- No `epidatatools` changes in this repository. The reference client in `examples/` shows
  the intended client behavior.

## Scope

v1 publishes exactly 33 programs, defined in `src/bls_index/scope.py`:

- 30 programs with native titles: `ap`, `bd`, `ce`, `ci`, `cm`, `cu`, `cw`, `cx`, `ei`,
  `ep`, `fm`, `ip`, `is`, `kv`, `la`, `le`, `ln`, `lu`, `mp`, `nb`, `nd`, `oe`, `or`,
  `pc`, `su`, `tu`, `wd`, `wm`, `wp`, `ws`.
- 3 programs with synthesized titles: `sm`, `jt`, `pr`.

Scope never comes from BLS directory listings or from a failed or missing source. The
remaining 21 programs (frozen twins, injuries and illnesses, standalone frozen programs)
and the excluded `nw` and case-characteristics programs are future work.

To add a program, open one pull request that:
- adds a builder, its tests, and the program code to `scope.py`
- adds the program's survey name
- adds the code to the `program` values in `data-dict.yaml`
- for a synthesized-title program only, adds it to the dictionary's list of synthesized
  programs in the `title_source` rule

A full build of the expanded scope must pass before the PR merges. The next weekly
release then includes the program.

## Catalog

One zstd-compressed Parquet file, `bls_index.parquet`, one row per series, written at
zstd level 19 (33 MB, against 47 MB at the default level, with the same read speed).
Column definitions, types and normalization rules are in
[`docs/schema-v1.md`](docs/schema-v1.md); machine-checkable constraints are in the
repository-root [`data-dict.yaml`](data-dict.yaml).

| Column | Type | Notes |
|---|---|---|
| `program` | string | BLS program code from scope, never inferred from the ID |
| `survey_name` | string | BLS name of the program's survey, such as "Consumer Price Index - All Urban Consumers"; one fixed value per program |
| `survey_aliases` | string, nullable | Other names people search for, such as "CPI; CPI-U", separated by `; `; one fixed value per program |
| `series_id` | string | Trimmed; unique across the catalog; compared exactly as spelled |
| `series_title` | string | Native title preserved as published, or synthesized from lookups |
| `title_source` | string | `native` or `synthesized` |
| `seasonal` | string | `SA`, `NSA`, or `unknown` |
| `begin_year`, `end_year` | int32, nullable | Four-digit source years |
| `end_period` | string, nullable | Source period code, such as `M08` |

Titles need not be unique. Schema version 1 is separate from the data-dict `$version`.
`begin_period` is deferred.

`survey_name` makes a series findable by its survey. Many native titles never name the
survey: CPI titles begin "All items in U.S. city average", so a search for "consumer
price index" finds nothing without it. Names come from a fixed table in code, one entry
per program in scope, taken from official BLS sources and checked by tests.

`survey_aliases` holds the other ways people refer to a survey: initialisms ("CES",
"JOLTS"), former names ("OES"), and informal names ("household survey"). Aliases are
our choice, not BLS text, so they stay out of the displayed `survey_name`. The same alias
can belong to several programs: "CPI" covers `cu`, `cw` and `su`. Each alias and its
reason is listed in [`docs/survey-names.md`](docs/survey-names.md). Because they live in
the catalog, they can improve with any weekly release, without a client update.

## Build

Each run builds all 33 programs from fresh downloads into a private run directory.

**Fetching.** Fetch each input once over HTTPS, with:

- a descriptive, contactable User-Agent from the `BLS_INDEX_USER_AGENT` secret (BLS
  returns 403 for agents containing "github")
- at most one request per second, measured from when the server answers the previous
  request
- timeouts, and bounded retries with backoff for 429, 5xx, transport errors and
  truncated bodies
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
to `unknown`, and record a warning in the run report. Extra or reordered columns do not
fail a program.

**Synthesized titles** (`sm`, `jt`, `pr`). Join `.series` to its lookup files and format a
reviewed title template. Fail the program on:

- a lookup key that matches zero rows, or more than one row
- a missing label
- a series ID that disagrees with the dimension codes used to build its title
- an output row count that differs from the `.series` row count

Unlike native IDs, synthesized IDs are checked against their dimension codes, because
those codes choose the title. The templates and lookup files are documented in
[`docs/synthesized-source-contracts.md`](docs/synthesized-source-contracts.md).

**Combined candidate.** Concatenate all 33 programs and check:

- the exact scope
- the canonical schema
- global `series_id` uniqueness

Then run the pinned `data-dict` `validate-spec`, `validate-meta` and `validate-data` on
the written Parquet. The dictionary is the single place for row rules that apply to every
program, including the four-digit year range. Row counts are kept in the run report as
diagnostics. A change in row count alone is not a failure.

If any program or any combined check fails, the run fails and publishes nothing.

## Publication

Catalogs are published as GitHub Releases of the public `Economic/bls-index` repository.

**Cadence.** A workflow builds the catalog every day, as a health check. A successful
daily build also publishes a release when the latest release's `built_at` is at least 6
days old, or when there is no release yet. With a daily schedule this publishes about
once a week. If a publish fails, the next day's run retries it. A manual dispatch can
force a publish. Only a run that built exactly the 33 programs in scope can publish; a
subset build is a diagnostic.

**A release** has the tag `catalog-YYYY-MM-DDTHHMMZ` (the UTC build start, to the
minute), targets the commit that built it, and carries two files:

- `bls_index.parquet`: the catalog
- `latest.json`: the manifest

The timestamp makes every tag unique, so a forced publish can follow a scheduled one on
the same day.

**Order.** The release stays a draft, invisible to clients, until everything is checked:

1. Delete any leftover draft or test release from an earlier run, together with its tag.
2. Create a draft release and upload both files.
3. Read the uploaded files' SHA-256 digests and sizes from the GitHub API. They must
   match the local files.
4. Publish the draft and mark it as the latest release.

Clients see a new catalog only after step 4. If any step fails, the run deletes the
draft and fails. If step 4's response is lost, the run re-reads the release. If the
release is published and latest, the run counts as success. Otherwise it fails, and the
next run tries again.

**Manifest fields** (`latest.json`):

- `manifest_version`: 1
- `schema_version`: 1
- `tag`: the release tag
- `built_at`: UTC time the build started downloading
- `published_at`
- `git_revision`: the commit that built the catalog
- `catalog`:
  - `url`: the tag-specific download URL,
    `https://github.com/Economic/bls-index/releases/download/<tag>/bls_index.parquet`
  - `sha256`
  - `bytes`
  - `rows`
- `programs`: a list of
  - `program`
  - `rows`
  - `inputs`, each with `file`, `bytes` and `sha256`

The catalog URL names the tag rather than "latest", so a client that read one manifest
always downloads the matching catalog, even if a new release appears in between.

**Retention.** After publishing, the run deletes releases beyond the newest 12, about
three months. Every deletion also deletes the release's tag. A failed deletion only logs
a warning: the catalog is already published, and the next publish tries again.

**Manual rollback.** Run `gh release edit <tag> --latest` on an older release. A rollback
lasts until the next publish. To hold it longer, disable the workflow's schedule until
the problem is fixed. The runbook documents this.

## Operations

- **Workflow.** One GitHub Actions workflow on a standard Linux runner, scheduled daily
  and dispatchable by hand, in concurrency group `bls-index-publish` with
  `cancel-in-progress: false`. A pending run may be replaced by a newer pending run,
  which is fine. It has three jobs:
  - **Build.** Holds only `contents: read` and the User-Agent secret. It builds the
    catalog and writes `latest.json`, then hands the run directory to the next job as a
    short-lived workflow artifact.
  - **Publish.** Runs only when publishing is due. Holds `contents: write` through the
    built-in `GITHUB_TOKEN`, and never sees BLS data except the finished files.
  - **Monitor.** Runs after the other two, always. It reports the run to the monitor
    (see Alerts).

  Splitting the jobs keeps the write token away from the job that parses downloaded
  files.
- **Branch protection.** `main` requires pull requests, so the workflow's write token
  cannot change code on `main`.
- **Alerts.** One healthchecks.io check (free tier) emails the maintainer:
  - **Failed runs.** The build job pings `/start` when it begins. The monitor job pings
    the success URL when the build succeeded and the publish job either succeeded or was
    skipped, and pings `/fail` otherwise. An explicit failure alerts within minutes.
  - **Missed runs.** With a 1-day period and a 1-day grace time, a missing success ping
    alerts within about 48 hours. That covers runs that never start, including GitHub
    disabling the schedule in an inactive repository.

  GitHub's own failed-run emails are a bonus, not a dependency.
- **Artifacts.** Workflow artifacts are temporary: the hand-off between jobs and the
  diagnostic report. Releases hold everything durable.
- **Credentials.** None beyond the `BLS_INDEX_USER_AGENT` secret, the healthchecks.io ping
  URL, and the built-in `GITHUB_TOKEN`.
- **Testing before launch.** A manual dispatch with a `test` option publishes a
  prerelease tagged `test-YYYY-MM-DDTHHMMZ`. Prereleases never become "latest", so
  clients never see it. It stays until the next run's cleanup, so it can be inspected
  and downloaded first.

## Clients

Clients start from two fixed URLs:

- manifest: `https://github.com/Economic/bls-index/releases/latest/download/latest.json`
- catalog: the `catalog.url` from that manifest

A reference client, `examples/find_bls.R`, follows these rules. Its signature is
`find_bls(search_string, survey = NULL, seasonality = NULL, limit = 1000,
refresh = FALSE)`. This is a deliberate breaking change from today's
`epidatatools::find_bls()`: `max_results` and `metadata` are gone. It always returns
`series_id`, `series_title`, `program`, `survey_name`, `seasonal`, `begin_year`,
`end_year` and `end_period`. Clients should:

- Cache the catalog in `tools::R_user_dir("epidatatools", "cache")`, and verify its
  SHA-256 against the manifest.
- Check the manifest at most once every 7 days, measured from the last check. If the
  checksum is unchanged, only reset the check date. If it changed, download the new
  catalog, verify it, swap it in, and delete the old one. `refresh = TRUE` checks now.
- Query the cached Parquet file in place, for example with `arrow::open_dataset`. Loading
  all 8.3 million rows into an R data frame takes about 2 GB and 14–29 s per search;
  querying in place takes about 0.3 s
  ([measurements](docs/evidence/2026-10-20-phase1-runner-build.md)).
- Search like this:
  - **Words.** Split the search string on spaces, and trim punctuation from the ends of
    each word. Every word must match in `series_title`, `survey_name` or
    `survey_aliases`, ignoring case. Escape regular-expression characters in words.
  - **Stemming.** Reduce each word to its English Snowball stem (`SnowballC` in R), and
    match any word that begins with the stem: "nurses" becomes "nurs" and matches nurse,
    nurses and nursing. A stem shorter than 4 characters is not used. The original word
    must then match as a whole word, so short words stay exact: "oes" would stem to "oe",
    and "CES" must not match "census". Longer initialisms can stem ("JOLTS" becomes
    "jolt"). On the 2026-10-20 catalog, matching JOLTS, OEWS, LAUS, SOII and ATUS by
    stem finds exactly the same rows as whole-word matching, so this is accepted.
  - **Word boundaries.** A match must start at the beginning of a word: "CES" matches 2
    titles as a word, but 769,239 inside words like "services". Hyphens separate words,
    so "CPI-U" also matches the chained "C-CPI-U". That is accepted: treating hyphens as
    part of words would stop "collar" matching "white-collar".
  - **Filters.** `survey` takes one or more program codes, such as `c("la", "ln")`,
    ignoring case, and filters `program`. `seasonality` takes one or more of `SA`, `NSA`
    and `unknown`. An unknown code is an error that lists the valid codes.
  - **Order.** Sort by title length (shortest first), then lowercased title, then series
    ID, comparing strings by bytes so the order is the same on every machine. Short titles
    tend to be the general series. Any change to this order is made here first.
  - **Limit.** Count the matches, sort, and keep the first `limit` rows (1,000 by
    default; `Inf` for all) before bringing them into R. A broad search such as "OEWS"
    matches 6 million rows: as a data frame that is 1.7 GB, and sorting it in R took 59 s.
    When results are cut, print the total and the matches per survey. For
    "unemployment rate" on the 2026-10-20 catalog: "13,163 matches; showing the first
    1,000. By survey: la 8,536, ln 4,197, fm 240, kv 138, jt 52."
  - **Later.** Quoted phrases, and "did you mean" suggestions when nothing matches.
- Allow enough time for a slow download. R's `download.file()` gives up after 60 s by
  default.
- If the network fails, keep using the cached catalog, and say how old it is.
- Treat a catalog whose `built_at` is more than 10 days old as stale, and say so.
- Send a User-Agent naming the client, and let users override the manifest URL with an
  option or environment variable.

## Accepted risks

These are deliberate. Reviews should not report them as defects.

1. **One broken program blocks every update.** All 33 programs then stop updating until
   the problem is fixed. Clients see `built_at` age.
2. **Single download.** Each file is downloaded once. A file that changes during the
   download and still passes every check can be published, and the next run corrects it.
3. **Valid but incomplete sources are published.** A structurally valid but incomplete
   source is published, because row-count changes are diagnostics, not failures.
4. **Native parsers check only the columns the catalog uses.** For native programs,
   BLS's internal consistency between IDs and their dimension columns is not checked.
5. **Weekly freshness.** A published catalog is up to about 8 days behind BLS, and a
   client that refreshes weekly can be about 15 days behind.
6. **Everything depends on GitHub.** Code, builds and data all live there. GitHub does
   not document throttling for anonymous release downloads. Moving the data elsewhere
   would need a client update.
7. **Rollback only within retention.** Only the newest 12 releases can be restored.
8. **Unclear publish outcomes can mislead alerts.** A run whose final publish response
   is lost may report failure although the release was published. The next run sees the
   release and does not publish again for 6 days.

## Decisions

- **Python, uv, polars,** with a pinned `data-dict-yaml` (2026-10-06).
- **Diagnostic row counts only:** no thresholds or warning state (2026-10-13).
- **Simplification** (2026-10-13), covering:
  - complete-only publication
  - scope in code
  - no journal
  - single download
  - name-based native parsing
  - manual recovery
- **Add `survey_name` before first publication** (2026-10-20), so the published v1
  schema includes it from the start. Write the catalog at zstd level 19.
- **Publish through GitHub Releases** (2026-10-20), replacing Cloudflare R2. This removes
  the Cloudflare dependency, R2 credentials, the staging bucket, cache configuration, and
  the conditional-write code. It keeps the data in the `Economic` organization.
  Superseded: R2 storage, the `bls-index` and `bls-index-staging` buckets, and the
  90-day lifecycle rule (2026-10-13).
- **Drop the discovery pointer** (2026-10-20). The release URL depends on the same
  repository the pointer did. Superseded: the GitHub Pages pointer (2026-10-07).
- **Build daily, publish weekly** (2026-10-20). Clients refresh at most weekly, so daily
  releases add little.
- **No change history** (2026-10-20). A weekly list of added and removed series was
  considered and dropped as not worth its cost.
- **Reference client queries in place with `arrow`** (2026-10-20).
- **Survey aliases and search rules** (2026-10-20). `survey_name` stays the official BLS
  name; initialisms, former names and informal names go in `survey_aliases`. Client
  search rules:
  - every word must match, stemmed, at the start of a word
  - sort by title length, then title, then series ID
  - a 1,000-row default limit, with counts by survey when results are cut
  - `survey` accepts several codes
  - a breaking change to `find_bls()`: no `max_results` or `metadata`, and always the
    extra columns

## Done when

1. `./scripts/check.sh` passes offline, locally and in CI.
2. The reference client finds expected series in a local build, including by survey
   name and alias.
3. The daily workflow has built all 33 programs on 7 consecutive days, and has published
   at least two weekly releases.
4. A failed build or publish leaves the latest release unchanged and alerts. The monitor
   alerts when no successful run happens within 48 hours.
5. From an outside machine, `curl` and the reference client download the latest catalog
   without credentials, and its checksum matches the manifest.
6. The runbook covers a manual rerun, a forced publish, rollback, adding a program,
   alerts, and costs.
