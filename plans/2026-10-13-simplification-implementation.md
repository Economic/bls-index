# Implementation plan: simplify, then publish (2026-10-13)

This plan implements the rewritten [`design.md`](../design.md). It replaces
[`docs/archive/plans/implementation-plan-v1.md`](../docs/archive/plans/implementation-plan-v1.md), which
is kept as a historical record. The reasoning is in
[`2026-10-13-simplification-review.md`](2026-10-13-simplification-review.md) and
[`../docs/reviews/2026-10-13-simplification-review.md`](../docs/reviews/2026-10-13-simplification-review.md).

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
- Task 1.8 (runner build, evidence note, checkpoint review) is in progress.

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

## Phase 2: Publish

### 2.1 Manifest

1. Document the manifest fields from `design.md` in `docs/manifest-v1.md`, with an
   example.
2. Write `manifest.py` (about 80 lines) to build the manifest dict from the build report,
   and to validate relative paths (the segment rule) in both directions.
3. Tests:
   - path rule accept and reject cases, including `..`, `%2e`, a leading `/`, a scheme,
     a query, and an empty segment
   - round trip from report to manifest

### 2.2 Object store (`object_store.py`)

Trim to four calls:

- `get(key) -> (bytes, etag) | Absent`
- `put(key, bytes)`
- `put_if(key, bytes, if_match=etag | if_none_match=True) -> committed | rejected | unknown`
- `head(key)`

Keep automatic botocore retries off for conditional writes.

### 2.3 Publish command (`bls-index publish RUNDIR`)

1. Read `latest.json`, keeping its ETag, or confirm it is absent. A read error that is
   not a 404 fails the run.
2. Upload `v1/catalog/bls_index-<sha>.parquet`. Read it back, and compare SHA-256 and
   size.
3. Upload `v1/manifest-<build_id>.json` (beside `latest.json`, so relative paths
   resolve the same way).
4. Write `latest.json` with `put_if`.
5. Handle the result:
   - **committed:** done
   - **rejected:** fail the run
   - **unknown:** re-read. If it holds our `build_id`, done. Otherwise retry once with the
     same condition. If that is still not committed, re-read once more for our
     `build_id`, then fail.
6. Exit nonzero on any failure. Print a summary.

### 2.4 Publish tests (moto plus the fault proxy)

- a first publication
- a second publication against the prior ETag
- 412 when the ETag changed
- a commit with the response dropped, then re-read as committed
- a timeout with no commit, then retry
- a failed read-back writes no `latest.json`
- a `latest.json` read error (403 or 500) fails before upload
- the manifest is never written before catalog verification: assert on the fault proxy's
  request log

That is about 10 tests.

### 2.5 Daily workflow (`.github/workflows/daily.yml`)

- Triggers: `schedule` (cron) plus `workflow_dispatch`, in concurrency group
  `bls-index-publish` with `cancel-in-progress: false`.
- Steps: ping healthchecks.io `/start`, install, build, publish, then ping the success
  URL. An `if: failure()` step pings `/fail`. Configure the check with a 1-day period
  and a 1-day grace time, with email alerts to the maintainer.
- Upload `report.json` as a 7-day diagnostic artifact, after the User-Agent grep.
- Secrets: `BLS_INDEX_USER_AGENT`, the R2 endpoint and keys, the bucket name, and the
  monitor URL.
- Default to the staging bucket. Production is a separate variable set only at launch.

### 2.6 Staging run

1. Attach the custom domain `bls-index-staging.benzipperer.org` to the existing
   `bls-index-staging` bucket, with `r2.dev` disabled. Confirm no Gate 0 test objects
   remain.
2. Run the workflow against staging three times, including one forced failure, such as
   a bad base URL.
3. Confirm the following:
   - the failure leaves `latest.json` unchanged and alerts
   - the monitor fires when pings stop
   - read-back time for the 47 MB catalog is recorded (this closes the old Gate 1 item)
   - `curl` and R download through the staging hostname, and the checksum matches

## Phase 3: Launch

1. **Buckets.** Attach the custom domain `bls-index.benzipperer.org` to the existing
   empty `bls-index` bucket, with `r2.dev` disabled. Add a cache rule for `/v1/catalog/*` and `/v1/manifest-*`, a short TTL for
   `latest.json`, and a lifecycle rule (90 days on prefixes `v1/catalog/` and `v1/manifest-`, a starting point
   to shorten later).
2. **Credentials.** Add scoped production credentials, and switch the workflow variable
   to production.
3. **First publication.** Run the first production publish by manual dispatch, then
   verify from an outside machine.
4. **Discovery pointer.** Add `pages/endpoint.json` through a reviewed PR and a Pages
   workflow that deploys only `pages/`, then verify that it resolves.
5. **Runbook.** Write `docs/runbook.md` covering:
   - credentials
   - a manual rerun
   - rollback (copy an archived manifest with `If-Match`)
   - adding a program
   - alerts and the monitor
   - expected costs
6. **Watch the schedule** for 7 days. Then announce the catalog.

## Decisions (2026-10-13)

The questions raised with the first draft of this plan were settled as follows.

1. **Branch.** Phase 0 is merged to `main` in one PR. (The three follow-up commits
   thought to be unmerged were already merged in PR #6.) Phase 1 starts on a new branch
   from `main`.
2. **Alerts.** One healthchecks.io check (free tier) with `/start`, success and `/fail`
   pings, a 1-day period and a 1-day grace time, and email to the maintainer. GitHub's
   failed-run emails are not relied on.
3. **Buckets.** Reuse the two existing buckets: `bls-index` for production, on
   `bls-index.benzipperer.org`, and `bls-index-staging` for staging, on
   `bls-index-staging.benzipperer.org`. There is no separate private bucket.
4. **PR `base_year`.** Warn, don't fail (task 1.3).
5. **Retention.** 90 days as a starting point. Shorten it once real rollback needs are
   known.
6. **Old docs.** Archive to `docs/archive/` in Phase 1, together with the code they
   describe (task 1.6). Keep `research/`.
7. **Historical `kv` layout.** Accepted. If that variant reappears, the build fails with
   a clear missing-column error.
