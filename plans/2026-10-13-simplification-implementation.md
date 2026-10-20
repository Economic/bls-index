# Implementation plan: simplify, then publish (2026-10-13)

This plan implements the rewritten [`design.md`](../design.md). It replaces the
[v1 implementation plan](https://github.com/Economic/bls-index/blob/pre-cleanup/docs/archive/plans/implementation-plan-v1.md). The reasoning
is in [`2026-10-13-simplification-review.md`](2026-10-13-simplification-review.md) and a
[second review](https://github.com/Economic/bls-index/blob/pre-cleanup/docs/reviews/2026-10-13-simplification-review.md). Older plans,
evidence and reviews are at the git tag `pre-cleanup`.

## Where we start

- All 33 builders work. A full build on the intended runner took 4.5 minutes, used
  4.6 GB peak RSS, and produced 8,315,248 rows and a 47 MB Parquet file.
- 538 offline tests pass in about 41 s.
- Nothing is published. Gate 0 verified R2 conditional writes.
- `main` includes the count-policy documentation and the handoff note (PR #6).

## Phase 0: Documentation and review tooling

Most of this was done in the change that added this plan.

1. Rewrite `design.md` around the smaller scope, with Non-goals and Accepted risks.
   **Done.**
2. Rewrite the `.roborev.toml` guidelines to weigh complexity, and disable automatic
   design review. **Done.**
3. Add a "superseded" note to the top of `docs/plans/implementation-plan-v1.md`, and
   update the README links and status line. **Done.**
4. Remove stale status claims from `docs/schema-v1.md`:
   - "the full-33 benchmark remains pending"
   - "native Parquet only for `ap`, `ce`, `cu`, `ln`, `oe`"
   - the deferred-verification and local-bundle sections that describe code Phase 1
     removes

   Rewrite the schema document to columns and normalization only. **Done.**
5. Mark `docs/phase1-handoff.md` and `docs/evidence/2026-10-13-phase1-open-checks.md` as
   historical. Gate 1 is closed by decision: remote read-back timing moves into the
   Phase 2 staging run. **Done.**
6. Add `tmp/` to `.gitignore`, and merge this phase to `main`. **Done.**

**Check:** a manual `roborev review --branch --panel design_only_panel` on Phase 0 alone,
to confirm the new guidelines produce proportionate findings. **Done** (roborev job 222,
2026-10-20). It produced four medium findings, all correctness gaps; all four are fixed
in `design.md` and tasks 1.3, 1.4 and 2.3.

## Phase 1: Simplify the build (no behavior change on current sources)

The goal is the same catalog rows from much less code. Every task ends with
`./scripts/check.sh` passing.

**Progress (2026-10-20), branch `phase1-simplify-build`:** tasks 1.0–1.7 are done.
- Source: 1,072 lines, down from 4,800.
- Tests: 154, running in 12 s, down from 538 in 41 s.
- `scripts/golden.py` confirms every program's rows match the old code on one full download.
- The combined catalog is identical: 8,315,248 rows.
- Local build time fell from 176 s to 7 s, and peak RSS from 4.6 GB to 3.8 GB.
- Task 1.8 is done. The runner build ([evidence](../docs/evidence/2026-10-20-phase1-runner-build.md))
  took 1 m 33 s for the whole job, against 4 m 44 s before. The checkpoint review's
  findings are fixed.

Deviations from the task list:
- The rewrite merged the builder modules into `schema.py` and `builders.py`. It also
  renamed `dry_build.py` to `build.py`, with the `build` command and `build.yml` workflow.
- A truncated download is retried per request, because there is no longer an
  input-set retry.
- The seasonal lookup files are no longer downloaded.
- Builder warnings (unexpected seasonal codes, PR `base_year` mismatches) appear per
  program in `report.json`.

### 1.0 Capture a golden output first

Before any code changes:

1. Download one full set of inputs locally, about 1.7 GB, into `tmp/golden-inputs/`.
2. Write a small script, `scripts/golden.py`, that runs the *current* builders on those
   inputs and writes each program's canonical frame to `tmp/golden/<program>.parquet`.
3. After each Phase 1 task, rerun the new code on the same inputs and compare with
   `frame.equals(golden)`. Any difference must be explained before moving on.

This replaces both the evidence JSON and the per-program revalidation scripts as the
proof that the refactor preserved output.

### 1.1 Fetcher (`http_source.py`)

- **Download each file once.** Remove the second read, `InputSet.rechecks`, and the
  `changed_during_build` path.
- **Remove these counters:** `received_body_bytes`, `verification_*`, `retry_*`, and
  `input_set_retries`. Also remove the `_download_classified` labels.
- **Remove concurrency:** `ThreadPoolExecutor`, `fetch_programs`, `max_concurrency`, and
  the lock-holding `RequestPacer`. Replace the pacer with one that sleeps until
  `last_start + interval`.
- **Keep:**
  - User-Agent validation
  - the loopback-only exception to the pacing floor
  - retries with backoff and `Retry-After`
  - the `Content-Length` check
  - `Accept-Encoding: identity`
  - the SHA-256 record per download
- **Return type:** `fetch_program(program, dir) -> dict[filename, Download]`, where a
  `Download` holds `path`, `url`, `bytes` and `sha256`.
- **Remove `EventLog`.** Use the standard `logging` module.

### 1.2 Native parser (`native_builders.py`, `native_parquet.py`)

- **Parse with polars** using all-string columns, `quote_char=None` and strict UTF-8.
  Find the needed columns by name from the trimmed header.
- **Checks:** the design's native-parser list. Implement the field-count check either
  with polars' strict column count (if it raises on ragged rows, verify this) or with one
  cheap byte-level pass that counts tabs per line.
- **Delete:**
  - `SOURCE_HEADERS`, `SEASONAL_SOURCE_CODES`
  - `SERIES_ID_LENGTHS`, `SERIES_ID_SEPARATORS`, `SERIES_ID_SEASON_CODES`
  - `SERIES_ID_COMPONENTS`, `SERIES_ID_FIELD_SLICES`
  - the per-character `unicodedata` loop
  - every snapshot copy and rehash
  - `_rename_directory_noreplace` and bundle reuse
  - the period-family validation
- **Keep `SERIES_ID_PREFIXES`.** Unify it with `scope.py`.
- **Seasonal mapping:** `S` to `SA`, `U` to `NSA`, everything else to `unknown`, logging
  a count of unexpected codes.
- **Output:** per-program bundles are dropped. The parser returns a frame, and the
  build keeps frames in memory until the combine step. If memory is a concern, keep one
  plain `write_parquet` per program in the run directory with no provenance sidecar.
- **Target:** about 150 lines for both files together, with OE parse time under 10 s.

### 1.3 Synthesized builders (`synthesized_builders.py`, `synthesized_parquet.py`)

- **One generic function** with signature
  `synthesize(program, series_df, lookups: dict[name, df], template) -> df`, built from
  polars joins.
- **Cardinality checks:**
  - lookup keys are unique (`is_duplicated`)
  - every series key matches a lookup row (an anti-join is empty)
  - the output row count equals the `.series` row count
- **Keep the ID-to-dimension checks** that `sm`, `jt` and `pr` have today (and SM's
  supersector-prefix check, which also chooses a title label): each series
  ID must agree with the codes used to build its title. Express them as one vectorized
  comparison per program. Test a code that exists in the lookup but disagrees with the
  ID.
- **Keep each program's join and template definition as data:** key column, label
  column, and template string.
- **Make the PR `base_year` check a warning.** It compares `base_year` with the index
  base year in the duration label. `base_year` is not published, and titles come from
  the label, so a mismatch is an inconsistency inside BLS's files (accepted risk 4).
  Record a mismatch count in the report; don't fail the program.
- **Delete:** the row-by-row dict loop, the duplicate `.series` decode,
  `_validate_program_input_set`, and the snapshot rehashing.
- **Keep the tests** for duplicate join keys and missing labels.

### 1.4 Combined candidate (`combined_candidate.py`)

- **Reduce `_validate_frame` to:** schema equality, a nonempty frame, `program` and
  `title_source` assignment, and global ID uniqueness. Row rules live in the builders and
  `data-dict.yaml`.
- **Add year range constraints to `data-dict.yaml`:** `begin_year` and `end_year`
  between 1000 and 9999 when present. This replaces the year checks in
  `_validate_frame` and covers native and synthesized programs alike. Test that a
  candidate with a two-digit year fails `validate-data`.
- **Data-dict:** run the `data-dict` binary from `PATH`, not `uv run --locked`, and move
  `data-dict-yaml` into the runtime dependencies.
- **Keep copying `data-dict.yaml` next to the candidate.** `validate-data` resolves the
  relative `parquet:` source path from the dictionary's directory. Drop the `replace`
  call, which replaces the string with itself.
- **Write directly** into the unique run directory, without staging and `os.link`.

### 1.5 Build command (`dry_build.py`, `cli.py`)

- **Rename `dry-build` to `build`.** Change the output to
  `RUNDIR/{report.json, bls_index.parquet}`.
- **Report contents:**
  - per program: rows, source files (bytes and SHA-256), seconds, and status with error
  - totals: seconds, catalog bytes, SHA-256 and rows
  - git revision
- **Write `report.json` once at the end**, plus once at failure. No per-program fsync
  checkpoints.
- **Delete:**
  - `_DiskSampler`, `_peak_rss`, `_query_metrics`, and the zero-result gate
  - the `notes` arrays
  - `_sanitize_event_value`, `_safe_failure_detail`, `_safe_url`, and
    `validate_dry_build_base_url`
- **Fold the three failure branches** into one `except` block with a `stage` variable.
- **Keep a `--base-url` option** for the local fixture server.
- **Keep the workflow's User-Agent grep** of artifacts. It is cheap and covers what the
  sanitizers were for.

### 1.6 Delete speculative and finished code

- **Delete:**
  - `r2_gate0.py` and the `r2-gate0` subcommand
  - `notifier.py`, `events.py`, `clock.py` (pass a `datetime` where tests need fixed
    time)
  - `probe.py`, `parse_probe.py`, and `.github/workflows/source-probe.yml`
  - `runner_info.py`: keep a `runner` block in the build report instead
  - `tests/harness/ordering.py`, `tests/harness/notifier.py`, and `tests/harness/clock.py`
- **Keep** `object_store.py` and `tests/harness/s3.py` (moto plus the fault proxy) for
  Phase 2. Remove their `EventLog` dependency now.
- **Archive docs together with the code they describe.** In the same commits, move
  `docs/native-source-contracts.md`, `docs/evidence/` (JSON and notes), and
  `docs/plans/implementation-plan-v1.md` to `docs/archive/`, and fix links. Keep
  `research/` in place.

### 1.7 Tests and fixtures

- **Delete:** `test_harness_ordering.py`, `test_r2_gate0.py`, the notifier and
  fake-clock tests, `test_measurement_instrumentation.py`, and `test_probe.py`.
- **Rename** `test_harness_http_source.py` to `test_http_source.py`. Cut the 9
  pacer/concurrency tests to 3: spacing, retry spacing, and the BLS floor.
- **Change exact-message `match=` checks** to the exception type plus one keyword.
- **Native tests:** one parametrized test over the 30 real samples (the row parses to
  `expected_canonical`), plus about 15 targeted failure cases:
  - a missing needed column
  - a ragged row
  - invalid UTF-8
  - an empty file
  - a blank, duplicate or wrong-prefix ID
  - a blank title
  - a bad year
  - an unexpected seasonal code mapped to `unknown`
  - an extra column accepted
  - a reordered column accepted
- **Stop reading `docs/evidence/*.json`** in tests.
- **Fixtures:**
  - Collapse `real_native/*.json` into one `expected_rows.json` with `program`, the raw
    line, and the expected canonical row.
  - Delete `native/full_revalidation_id_rows.json`, `native/constructed_rows.json` and
    `native/cx-boundary.series`, plus the `test_cx_boundary.py` that uses it.
  - Keep `two_program/` as the HTTP-served tree.
- **Target:** about 150–200 tests, under 10 s.

### 1.8 Verify

1. Rerun the golden comparison (1.0) for all 33 programs.
2. Run `./scripts/check.sh`.
3. Dispatch one full build on the GitHub runner and record total time, peak memory from
   `/usr/bin/time -v` in the workflow step, and catalog bytes in a short evidence note.
4. Run a manual `checkpoint_panel` review of Phase 1.

**Expected size after Phase 1:** about 1,200–1,500 lines of source, down from 4,800.

### 1.9 Add `survey_name` and raise compression (decided 2026-10-20)

Do this before Phase 2, so the first published schema includes the column.

- **Names.** Add `SURVEY_NAMES: dict[program, str]` to `scope.py`, one entry for each
  of the 33 programs. Take each name from an official BLS source, preferably the
  survey list on BLS's series ID format help page or the program's `<program>.txt` file
  (`cx.txt` returned 404 in October, so `cx` needs another BLS page). Record the source
  for each name in a short note in `docs/`. Do not fetch names at build time.
- **Schema.** Add `survey_name` (string, required) after `program` in
  `CANONICAL_SCHEMA`, in `canonical_rows`, in `docs/schema-v1.md`, and in
  `data-dict.yaml`. In the dictionary, also assert that every program has exactly one
  survey name.
- **Compression.** Write the combined catalog at zstd level 19. Measured on the
  2026-10-20 catalog: 32.8 MB instead of 47.2 MB, the same read time, and about 70 s
  more to write.
- **Tests.** Check that every program in scope has a name, and none outside it. Check that
  a build gives every row its program's name.
- **Verify.** The golden comparison now differs by one column. Compare all other columns
  with `scripts/golden.py`; it may need a column filter. Then confirm the new column has
  one value per program, and record the catalog's size.

### 1.10 Reference client prototype (decided 2026-10-20)

Write `examples/find_bls.R` before Phase 2, against a local build, to test the schema
and search behavior while they can still change. It is a reference for `epidatatools`,
not a package.

- **Signature.** `find_bls(search_string, max_results = 20, survey = NULL,
  seasonality = NULL, refresh = FALSE)`, returning a tibble with `series_id`,
  `series_title`, `survey_name` and `seasonal`. This matches today's function plus
  `refresh`.
- **Search.** Query the cached Parquet in place with `arrow::open_dataset`. Every word of
  `search_string` must appear, case-insensitively, in `series_title` or `survey_name`.
  `survey` filters `program`, and `seasonality` filters `seasonal`.
- **Ranking.** Try a few orderings on realistic queries and pick one: shortest title
  first; seasonally adjusted first; by program then ID. Examples: "unemployment rate",
  "consumer price index", "registered nurses", "average hourly earnings manufacturing",
  "quits". Show the maintainer the top 20 for each before choosing.
- **Row groups.** Check whether writing the Parquet in program order with smaller row
  groups makes `survey = "ln"` skip OE's 6 million rows. Adopt it only if the speedup is
  noticeable.
- **Cache and refresh.** Implement the client rules in `design.md` (weekly check, checksum,
  swap, offline fallback, download timeout). Until Phase 2 exists, point it at a local
  manifest and catalog. Phase 2 tests the download path against a test prerelease.
- **Done when** each example query returns sensible top results in under a second, and
  any schema change it motivates has been made in the build.

## Phase 2: Publish through GitHub Releases

### 2.1 Remove the R2 code

**Done 2026-10-20** (all but the optional operator step).

- Delete `object_store.py`, `tests/test_object_store.py`, `tests/harness/s3.py`, and
  the moto fixtures in `conftest.py`.
- Remove `boto3` and `moto[server]` from `pyproject.toml`, and update `uv.lock`.
- Operator, optional: delete the R2 buckets `bls-index` and `bls-index-staging` and their
  API token, or keep them unused.

### 2.2 Manifest and publish decision (`manifest.py`)

- `bls-index manifest RUNDIR --tag TAG --repo Economic/bls-index` writes
  `RUNDIR/latest.json` with the fields in `design.md`. It refuses a run whose
  `report.json` is not `success`, or whose `requested_programs` is not exactly
  `scope.INITIAL_PROGRAMS`.
- `bls-index publish-due [PREVIOUS_MANIFEST]` prints `due=true` when the previous
  manifest's `built_at` is at least 6 days old, or when no previous manifest is given,
  and `due=false` otherwise. The workflow appends this to `$GITHUB_OUTPUT`. The command
  exits 0 either way, and nonzero only on an error such as an unreadable manifest, so an
  ordinary day without publishing never counts as a failure.
- Tests: refusal of failed and subset runs; manifest fields and the catalog URL; the
  6-day boundary; no previous manifest.

### 2.3 Publish script (`scripts/publish.sh`)

A short `gh` script, run by the publish job:

Tags are `catalog-YYYY-MM-DDTHHMMZ`, or `test-YYYY-MM-DDTHHMMZ` for a test run, from
the build's start time. Every deletion uses `gh release delete --cleanup-tag`.

1. Delete any draft release, and any `test-` prerelease, left by an earlier run.
2. `gh release create TAG --draft --target <sha>` with `bls_index.parquet` and
   `latest.json`. For a test run, add `--prerelease`.
3. Read the uploaded files' digests and sizes with `gh release view --json assets`, and
   compare them with the local SHA-256 and sizes. On a mismatch, delete the draft and
   fail.
4. `gh release edit TAG --draft=false --latest` (without `--latest` for a test run). If
   this fails, re-read the release. If it is published (and latest, for a real run),
   continue; otherwise delete the draft and fail.
5. Delete `catalog-` releases beyond the newest 12. A test release stays until the next
   run's step 1, so it can be inspected and downloaded first.

**Test.** One offline pytest runs the script with a stub `gh` first on `PATH`. The stub
records every call and returns canned JSON. Two cases:
- matching digests: the draft is published
- a wrong digest: `release edit --draft=false` is never called, and the draft is deleted

This guards the design's one high-severity rule. The test-prerelease runs in 2.5
exercise the script against real GitHub.

### 2.4 Daily workflow (`.github/workflows/daily.yml`)

- **Triggers.** `schedule` (daily) plus `workflow_dispatch`, with inputs `publish`
  (`auto`, `force` or `test`). Use concurrency group `bls-index-publish` with
  `cancel-in-progress: false`.
- **Build job** (`contents: read`, the User-Agent secret):
  1. Ping healthchecks.io `/start`, then install and build.
  2. Download the latest release's `latest.json` if one exists, and run `publish-due`.
  3. Write `latest.json` with `bls-index manifest`.
  4. Upload the catalog, manifest and report as a 1-day artifact for the publish job,
     and the report alone as a 7-day diagnostic artifact, after the User-Agent grep.
- **Publish job** (`contents: write`). Runs when publishing is due, forced, or a test:
  download the artifact and run `scripts/publish.sh`.
- **Monitor.** A final step pings the success URL when every job succeeded, and an
  `if: failure()` step pings `/fail`.
- **Secrets.** Two: `BLS_INDEX_USER_AGENT` and the healthchecks.io ping URL.
- **Replace `build.yml`.** The daily workflow with a manual dispatch covers it.

### 2.5 Test before launch

1. Create the healthchecks.io check: 1-day period, 1-day grace time, email alerts.
2. Dispatch with `publish: test`. Confirm that a `test-` prerelease appears and never
   becomes "latest". Before the next run, confirm that the reference client downloads
   and verifies a catalog from the prerelease's tag-specific URL.
3. Dispatch with `publish: test` again, on the same day. Confirm that the first test
   release and its tag are gone, and that a second one appears with a new tag.
4. Dispatch once with a forced failure, such as a bad base URL. Confirm that no release
   is created and `/fail` sends an email.
5. Pause the workflow for more than two days, or point the check at a test URL, and
   confirm that the missed-run email arrives.
6. Record the results, including publish duration, in a short evidence note.

## Phase 3: Launch

1. **Branch protection.** Require pull requests for `main`, and confirm that a workflow
   token cannot push to it.
2. **First release.** Dispatch with `publish: force`. From an outside machine, check that
   `curl -L .../releases/latest/download/latest.json` works without credentials, and
   that the reference client downloads the catalog and its checksum matches.
3. **Runbook.** Write `docs/runbook.md` covering:
   - a manual rerun
   - a forced publish
   - rollback with `gh release edit <tag> --latest`, and pausing the schedule to hold it
   - adding a program
   - the monitor and alerts
   - costs (none expected for a public repository)
4. **Watch.** Let 7 daily builds and two weekly releases run. Then announce the catalog,
   and hand the reference client to the `epidatatools` maintainers.

## Decisions

### 2026-10-13

The questions raised with the first draft of this plan were settled as follows.

1. **Branch.** Phase 0 is merged to `main` in one PR. (The three follow-up commits
   thought to be unmerged were already merged in PR #6.) Phase 1 starts on a new branch
   from `main`.
2. **Alerts.** One healthchecks.io check (free tier) with `/start`, success and `/fail`
   pings, a 1-day period and a 1-day grace time, and email to the maintainer. GitHub's
   failed-run emails are not relied on.
3. **Buckets.** Reuse the two existing buckets for production and staging. Superseded
   on 2026-10-20 by GitHub Releases.
4. **PR `base_year`.** Warn, don't fail (task 1.3).
5. **Retention.** 90 days as a starting point. Superseded on 2026-10-20: keep the newest
   12 weekly releases.
6. **Old docs.** Archive to `docs/archive/` in Phase 1, together with the code they
   describe (task 1.6). Keep `research/`. Superseded on 2026-10-20: `docs/archive/` and
   `docs/reviews/` were deleted, and remain at the git tag `pre-cleanup`.
7. **Historical `kv` layout.** Accepted. If that variant reappears, the build fails with
   a clear missing-column error.

### 2026-10-20

8. **Survey name.** Add `survey_name` before the first release (task 1.9), and write the
   catalog at zstd level 19.
9. **Hosting.** Publish through GitHub Releases instead of R2 (Phase 2).
10. **Discovery.** Drop the GitHub Pages pointer.
11. **Cadence.** Build daily, and publish when the latest release is at least 6 days old.
    Clients check for a new catalog at most weekly.
12. **Change history.** Dropped: no list of added or removed series.
13. **Client.** Prototype `examples/find_bls.R` before Phase 2 (task 1.10), querying the
    Parquet in place with `arrow`.
14. **Retention.** Keep the newest 12 releases.
