# Simplification review: bls_index (2026-10-13)

Scope: `design.md`, `docs/plans/implementation-plan-v1.md`, `docs/`, `src/`, `tests/`,
workflows, and `.roborev.toml`, at `3513fb6` on `feature/phase1-native-builders`.

## The goal, restated

The goal is to replace the broken BLS Data Finder behind `epidatatools::find_bls()`. Once a
day, download about 1.7 GB of BLS `.series` files, write a 47 MB Parquet file of
about 8.3M `(series_id, title, seasonal, years)` rows, and put it at a stable URL with a
small manifest. The full build already runs in **4.5 minutes** on a free runner.

The stakes are low. If the catalog is a day or two stale, a user finds a series ID
slightly late, and they then pull the data from the BLS API by ID anyway. If one program
fails for a day, that program's search results are a day old. No money, legal record, or
irreversible state is involved.

The project so far has **17,000 words of design and plan**, **~4,800 lines of source**,
**~4,000 lines of tests** (538 tests), and eight evidence JSON files. None of this
publishes anything yet. Most of the complexity protects against failure modes that
don't matter at these stakes, or that a daily rebuild already fixes.

## Root cause: the review loop ratchets complexity

`.roborev.toml` runs a GPT-6 design review on every change to `design.md` or the plan,
plus a code review on every commit. Its instructions say to "flag ambiguity,
contradictions, missing requirements… unhandled failure modes", and they treat as *high
severity* anything that could misclassify an ambiguous storage result.

A reviewer told to find unhandled failure modes will always find one more. Each finding
was resolved by **adding** a clause, a state, or a test, never by removing a requirement.
The git log shows this clearly: "Bind manual release approval to published scope", "Test
scope approval across repeated program lists", "Pause publication through bucket cutover
and close path loopholes", "Hold the pacing slot through dispatch…". The design reads
like the accumulated answers to adversarial questions, not like a spec for the product.

**Recommendation:** change the review guidelines so that simplicity is a goal. Tell the
reviewers to flag complexity that the project's stakes don't justify, as well as missing
cases. Treat "could this requirement be deleted?" as a valid finding. Don't run design
review on every doc commit. At minimum, add a "Non-goals / accepted risks" section to
`design.md` that reviewers must respect. Without this change, any simplification below
will slowly grow back.

---

## 1. Design and plan: what to cut

### 1a. Replace the manifest write outcome protocol (the biggest item)

The design has a durable private journal, `prepared → submitting →
resolved_committed/resolved_noncommitted` states, terminal markers that are never deleted,
reconciliation through uncached reads, fail-closed stops, and three cross-run crash and
recovery test cases. That is two-phase-commit machinery for **one writer that runs once a
day under a GitHub concurrency group**.

Simpler model:

1. Upload immutable content-addressed objects and verify them by read-back (keep this).
2. `PUT latest.json` with `If-Match: <etag read at start>`. Use `If-None-Match: *` for
   the first publication.
3. On success, you're done. On a 412, someone else wrote it, so fail loudly. On a timeout
   or unknown result, GET `latest.json`. If it contains this run's `build_id`, it
   committed. If not, fail the run, and tomorrow's run rebuilds from scratch.

This is safe because every daily run rebuilds everything from fresh sources and the
manifest is idempotent content. An unknown outcome costs, at worst, one day of
staleness. No journal, no lifecycle states, no recovery step before downloads.

Even the CAS is optional: GitHub's `concurrency: cancel-in-progress: false` already
serializes writers. Keep CAS because it is one header and Gate 0 already verified it,
but don't build anything on top of it.

### 1b. Remove scope release, scope_revision and fingerprints

Scope changes (adding the 21 future programs) happen **a few times in the project's
life**, always by the maintainer. The design specifies a separate workflow, operator
confirmation tied to a `(scope_revision, required_programs)` fingerprint, rechecks
before downloads and again before the switch, and a test that A→B→A rejects the original
approval.

Simpler model: **scope is a constant in `scope.py`, changed by a reviewed PR.** The daily
build builds what's in the repo. Write `required_programs` into the manifest as
information, not as configuration the daily run reads back. Merging the PR is the
approval. This removes the rule that daily scope comes only from the manifest, which
forced a bootstrap special case ("before first publication, use the fixed 33") and much
of the plan's Phase 3.

The risk the current design guards against, "a future milestone list gets built by
accident", is handled by code review of a single tuple.

### 1c. Collapse status to two states, or drop per-program fallback

There are now three statuses (`fresh` / `degraded` / `stale`) with precedence rules,
`last_complete_successful_source_verification_at`, per-program last-good records,
per-program attempt records, and special rules for rollback freshness. Pick one of two
options:

- **Option A (simplest):** all-or-nothing. If any program fails, don't publish, and
  yesterday's manifest stays. Clients see `built_at` and decide whether it is stale.
  There is no last-good, no `degraded`, and no fallback selection. The cost is that one
  broken BLS file blocks updates for all 33 programs until it is fixed. With the current
  strict parsers (see 2a), that will happen often, so this option pairs with loosening
  the parsers.
- **Option B:** keep per-program fallback, but implement it as "reuse the previous
  manifest's per-program Parquet for a failed program". The manifest's `programs` list
  already names those files, so no separate last-good registry is needed. Status is
  `built_at` per program plus one boolean `complete`.

Either option deletes the 48-hour boundary tests, the rollback freshness rules, and most
of acceptance checks 6, 8, and 9.

### 1d. Make rollback a manual git or CLI action, with no `previous` record

The `previous` record with grace expiry, a same-scope-only rule, last-good re-pinning on
rollback, and "post-expiry recovery" are all there so an operator can undo a bad
publication. For a catalog that rebuilds daily, the realistic fix is to fix the bug and
rerun, or to re-point `latest.json` at an older content-addressed file by hand. Keep old
objects for N days with an **R2 lifecycle rule** (age-based expiry) instead of a custom
cleanup job that reads protected references under a lock.

### 1e. Drop the relocation and host-move rehearsal

The bucket-cutover procedure, the old-host redirect verification, and the staging
rehearsal of a host move (both same-bucket and cross-bucket) cover an event that may
never happen. Keep the GitHub Pages `endpoint.json` pointer and relative manifest paths.
Those decisions are cheap and good. Delete the cutover procedure from the design. If a
move ever happens, write the procedure then.

### 1f. Trim the client contract

The `epidatatools` client rules (pointer TTL, once-per-session, ETag revalidation,
Retry-After) belong in the client's repo. One paragraph here is enough: "fetch
`endpoint.json`, then `latest.json`, verify the SHA-256, cache by checksum."

### 1g. Daily double download

Every input is downloaded twice and compared by SHA-256 to detect mid-download changes.
That doubles BLS traffic (3.3 GB/day) and download time (105 s of the 269 s total). A
`Content-Length` check already catches truncation, and parsing catches structural
damage. BLS files change at most a few times a day, so a file swapped mid-download would
most likely fail parsing, and if it didn't, the next day's run fixes it. **Download
once.**

### 1h. What to keep

Keep the following decisions:

- one Parquet file plus `latest.json`
- content-addressed immutable objects
- upload and read-back before the manifest write
- R2 behind a custom domain
- the GitHub Pages discovery pointer
- relative manifest paths
- `data-dict.yaml`
- a User-Agent from a secret
- 1 request/second pacing
- the fixed v1 scope of 33 programs
- duplicate titles allowed
- no liveness inference

### 1i. A shorter Phase 2–4

With 1a–1g applied, the remaining work is roughly:

1. `bls-index build --out DIR` (the current dry-build, simplified).
2. `bls-index publish DIR`: upload per-program and combined Parquet, read back, then
   write `latest.json` with CAS.
3. A daily workflow with cron, a concurrency group, an R2 secret, and an alert that
   fires when the workflow fails (GitHub's own failure emails, or one webhook step).
4. The Pages `endpoint.json`, a cache rule, and a short runbook.

That is probably a few hundred lines of code and 20–40 tests. The current plan's Gates 2
and 3 plus ten acceptance checks would take many times that.

---

## 2. Code: what to simplify

### 2a. Native parsers validate far more than the catalog needs (`native_builders.py`, 758 lines)

The catalog stores only `series_id`, `series_title`, `seasonal`, `begin_year`,
`end_year`, and `end_period`. The parser goes further and:

- **Rebuilds each series ID from its dimension columns** (`SERIES_ID_COMPONENTS`,
  `SERIES_ID_FIELD_SLICES`, special cases for `ep` hyphens, the `ce` 6-digit slice, and
  the `wp` `ILF/IND→03` aliases), then rejects the whole program if any row disagrees.
  The catalog never uses those dimension codes.
- Enforces per-program **ID length ranges** (`SERIES_ID_LENGTHS`) taken from observed
  samples.
- Requires an **exact header tuple** for every program, so any new BLS column fails the
  program.
- Requires an **exact seasonal code set** per program.

Each of these is a way for a harmless BLS change to fail a daily build. Under the
all-33-or-nothing first publication, any one of them blocks launch. None of them
protects the catalog's actual contract.

**Recommendation:**

- Look up the needed columns *by name* from the header: `series_id`, `series_title`,
  `seasonal` if present, and the year and period columns. Fail only if those are missing.
- Require nonempty, trimmed, unique IDs that start with the program prefix.
- Require nonempty titles and four-digit years.
- Map seasonal `S→SA`, `U→NSA`, and anything else to `unknown`.

This replaces about 400 lines of tables and expressions with about 40, and removes the
need for most of `docs/native-source-contracts.md` (181 lines) and the
revalidation JSON fixtures.

### 2b. Each input is hashed about 11 times and copied 3 times

For one native `.series` file, the code does the following, in order:

1. The download hashes it.
2. The redownload hashes it again.
3. `_verify_source` "before staging".
4. `_copy_verified_snapshot` copies and hashes it.
5. `parse_native_series` copies it again, to a second snapshot, and hashes it.
6. `before_validation_sha256`.
7. `after_parse_sha256`.
8. `_verify_source` "after parsing".
9. `_verify_records` "before publication", up to three more times.

All of this guards against **a file in a private temp directory changing while the
process reads it**. Nothing else writes there. Delete all of it: hash once at download
and record it in provenance.

The same applies to `_rename_directory_noreplace`, which calls `renameat2` through
`ctypes` and is Linux-only. Atomic no-replace publication of a local per-run directory
is unnecessary. Use `os.replace`, or write directly, since every run gets a fresh
`uuid` directory.

### 2c. The OE parse is slow because of a Python per-character loop

`_validate_raw_file` (`native_builders.py:452`) decodes every line in Python and calls
`unicodedata.category()` on **every character** of the 1.26 GB `oe.series`. That accounts
for most of OE's 90 s `parse_seconds`, which is a third of the total build time. Polars'
`read_csv(encoding="utf8")` already fails on invalid UTF-8 and checks field counts. If
control characters matter, check them with one vectorized `str.contains(r"[\x00-\x08…]")`
on the title column. Expected gain: OE drops from about 90 s to about 5 s.

### 2d. Validation runs three times

The same rules are checked:

1. in the builders (`native_builders.py`, `synthesized_builders.py`)
2. again in `combined_candidate._validate_frame` (ID pattern, seasonal set, seasonal-ID
   consistency, year range, period regex, period without year)
3. a third time in `data-dict.yaml` (unique, required, trimmed, title nonempty,
   begin ≤ end)

Keep **one** set of row checks in the builders, plus combined-level uniqueness and the
data-dict run. `_validate_frame` can shrink to a schema check plus the program/title_source
assignment.

Note also that `combined_candidate.py:301` calls
`dictionary_text.replace(_DICTIONARY_SOURCE, "parquet: bls_index.parquet")`, which
replaces the string with itself, so it does nothing. Delete that call. Do keep copying
the dictionary next to the candidate Parquet: `validate-data` resolves the relative
`parquet:` path from the dictionary's directory, so the copy is what makes validation
read the candidate. (Correction made 2026-10-13, after drafting the implementation plan.)

### 2e. Input-set metadata is re-validated defensively

`_validate_input_set` (native) and `_validate_program_input_set` (synthesized, 45 lines)
re-check that an `InputSet` built by our own `HttpSource` has HTTP 200, a valid SHA-256
regex, `bytes` as a non-bool int, URL path parts matching, and rechecks matching. These
are internal invariants of one process. If 1g is adopted, `rechecks` disappears. Pass
`program → {filename: Path}` to the builders and drop the `InputSet` coupling.

### 2f. Too much instrumentation in `dry_build.py` (610 lines) and `http_source.py`

The following were useful **once**, to answer "does this fit on a runner?" That
question is answered: 4.6 GB RSS on 16 GB, 2.7 GB disk on 86 GB free, 4.5 minutes. They
can go now:

- `_DiskSampler` (a background thread sampling disk usage every 0.25 s)
- `_peak_rss` with `RUSAGE_SELF`/`RUSAGE_CHILDREN`, unit normalization, and scope notes
- seven traffic counters in `HttpSource` (`verification_body_bytes`, `retry_body_bytes`,
  `verification_request_attempts`, …), threaded through `_download_classified`
- `_query_metrics`, plus the rule that a full-scope run *fails* if a benchmark query
  returns zero
- free-text `notes` arrays explaining measurement caveats
- `_write_checkpoint` after every program, with `fsync` and atomic replace
- `_sanitize_event_value` / `_safe_failure_detail` / `_safe_url` redaction (the
  User-Agent is never placed in errors; the workflow already greps artifacts for it)

The "zero results fail the build" rule is a benchmark assertion acting as a production
gate. Move it to a test against the fixture, or drop it.

Suggested report: per program, record rows, source bytes, SHA-256, seconds, and errors.
Overall, record total seconds and the combined bytes and SHA-256. This would make
`dry_build.py` about 150 lines.

The three failure branches in the program loop (`InputSetError`, `OSError`, and
`Exception`) duplicate the same five statements. Fold them into one `except` block with
a `stage` variable.

### 2g. Delete or park speculative Phase 2 code

- `object_store.py` (251 lines), `r2_gate0.py` (213 lines), `notifier.py`, `events.py`,
  `clock.py`, and the moto, fault proxy, and ordering harness in `tests/harness/` were
  built in Phase 0 for a publication state machine that doesn't exist yet. Gate 0 is
  recorded. Once 1a–1d shrink Phase 2, most of this harness (fault proxy, event-order
  assertions, notifier double) has no consumer. Delete `r2_gate0` and the
  ordering/notifier harness now. Rewrite `object_store` as a 50-line `put_if`/`get`
  wrapper when Phase 2 starts.
- `EventLog` with thread locks and JSON snapshotting: replace it with `logging`.
- `Clock` protocol: the only real need is a fixed `built_at` in tests. Pass a `datetime`
  argument instead.
- `probe.py` + `parse_probe.py` + the `source-probe.yml` workflow: Gate 0 is complete,
  and `dry-build` now does a strict superset. Delete them, or fold `--keep-files` into
  `build`.
- `runner_info.py`: it duplicates `dry_build.runtime_environment` (and `_memory_bytes`
  duplicates `_meminfo`). Keep one.

### 2h. Concurrency that isn't used

`HttpSource` has a `ThreadPoolExecutor`, `max_concurrency`, a thread-safe `RequestPacer`
that holds a lock across dispatch, and `fetch_programs()`. Dry-build forces
`max_concurrency=1`, and the 1 request/second cap makes parallel downloads pointless
anyway. Remove the thread pool and `fetch_programs`. Keep a plain `time.sleep` pacer.

### 2i. Smaller points

- `combined_candidate._run_data_dict_checks` shells out to `uv run --locked data-dict`
  from inside the library. That requires `uv` and the *dev* dependency group in
  production. Call the `data-dict` binary on `PATH`, and move `data-dict-yaml` to the
  main dependencies.
- `validate_dry_build_base_url` (credentials, query, and fragment rejection): there is
  one URL, and it comes from a constant or a test fixture. Drop it.
- `write_combined_candidate` stages into a temp dir and then `os.link`s to "never
  replace". The run directory is unique per run, so write directly.
- In `synthesized_builders.py`, PR is parsed row by row in Python dicts, while SM/JT use a
  separate path. All three are "series join lookups → format template". One generic
  `synthesize(series, lookups, template)` with polars joins and a
  `validate="m:1"` cardinality check would replace most of the 529 lines.

---

## 3. Docs and evidence

- `design.md` (10k words) is written as dense paragraphs that each restate the same
  rules (scope release appears in nearly every bullet). After the cuts above, rewrite it
  at about 1,500 words: Goal, Non-goals, Artifact & schema, Manifest, Daily build,
  Serving, Accepted risks.
- `docs/plans/implementation-plan-v1.md` (7k words) mostly repeats the design. Replace
  it with a short task list per phase.
- `docs/evidence/` contains eight JSON files plus per-gate prose that hedges every number
  ("sampled peak; not an absolute guaranteed maximum", "not a billing audit"). Keep the
  benchmark summary. The rest is history and can live in git.
- `docs/phase1-handoff.md` and `phase1-open-checks.md`: the "open checks" (remote
  read-back timing, Actions usage audit) aren't needed to proceed. Remote read-back of a
  47 MB file takes seconds. Close Gate 1.
- README: the dry-build section is about 40 lines on RSS units and sampling caveats.
  Cut it to the commands.

---

## 4. Tests

There are 538 tests. They take 41.5 s of wall time but only 14 s of CPU; most of the
rest is spent in harness timeouts. 12 of the 15 slowest tests are HTTP-harness or
object-store fault tests.

**Delete: speculative harness for a publication path that doesn't exist yet** (about
65 cases, 1,100 lines of tests and harness, plus the `boto3`/`moto` dependencies):

- `test_harness_object_store.py` (33 cases), `harness/s3.py`, and the moto fixtures in
  `conftest.py:76-104`.
- `test_harness_ordering.py` (14 cases): it tests the harness's own manifest-ordering
  assertion, for a manifest that doesn't exist yet. Also delete `harness/ordering.py`.
- `test_r2_gate0.py` and the `r2-gate0` CLI subcommand: Gate 0 is done.
- The notifier tests and `harness/notifier.py`, plus
  `test_fake_clock_exact_48_hour_boundary`, which tests the fake clock itself.

**Delete or trim: tests of benchmark instrumentation:**

- Delete `test_measurement_instrumentation.py` (byte counters), or keep only one test.
- In `test_cli.py:101-170`, remove the asserts on `sampling_interval_seconds == 0.25`,
  the literal caveat phrases "not an absolute guaranteed maximum" and "not a concurrent
  aggregate", and the `dictionary_check_seconds` keys. Keep status, row count, and files.
- `test_full_initial_scope_requires_representative_search_results` goes away with the
  rule it tests (2f).

**Trim: tests that pin incidental detail:**

- About 110 `match=` checks pin exact error text. Match on the exception type plus one
  keyword instead.
- `test_native_builders.py` has 248 cases, from stacked parametrization over 30, 26, and
  14 programs. After 2a, roughly 60–80 cases would cover the same ground. Two of its
  tests read `docs/evidence/*.json` (`:283`, `:550`), which ties the suite to research
  records.
- `test_real_native_samples.py` mostly checks the fixtures' own metadata (SHA-256,
  `two_read_sha256_match`, row-number math). Keep only "the sample row parses to the
  expected canonical row".
- `test_combined_candidate.py:115-188` re-tests builder rules, the test-side mirror of
  2d.
- The native and synthesized Parquet tests include 5–6 source-mutation and publish-race
  tests. Those races can't happen in a single runner that owns its directory.
- The 9 pacer/concurrency tests in `test_harness_http_source.py:354-508` guard
  multi-worker races, but production runs single-worker. Keep about 3 of them. Also
  rename the file to `test_http_source.py`, since it tests production code.
- Merge `test_cx_boundary.py` into `test_native_builders.py`.

**Fixtures** (788 KB in total):

- `real_native/*.json` are 30 provenance records. Only `raw_fields` and
  `expected_canonical` are used. Collapse them to one small expected-rows file.
- `native/constructed_rows.json` and `full_revalidation_id_rows.json` are research
  output turned into fixtures. Inline what's needed, or drop them along with the ID
  reconstruction rules (2a).
- `ap.series` exists in three fixture trees. Keep `two_program/` as the one HTTP-served
  tree.

**Keep:** the synthesized-builder tests (lookup cardinality and duplicate join keys are
the real risks there), the core HTTP retry, truncation, and 404 tests, the scope tests,
the duplicate-title and ID-collision tests, the data-dict accept/reject tests, and the
live smoke test.

Rough target: 150–200 tests running in under 10 s.

Also delete the stale `tests/__pycache__/test_zz_*.pyc` files.

---

## Suggested order of work

1. **Decide the policy questions below.** Most of the savings come from design choices,
   not code.
2. Change the roborev guidelines (or pause design review) so the cuts don't grow back.
3. Rewrite `design.md` and the plan to the smaller scope.
4. Simplify the Phase 1 code (2a–2f, 2h, 2i) and the matching tests. Rerun one full-33
   dry build to confirm the row counts are unchanged (8,315,248) and check the new
   runtime.
5. Delete the speculative modules and harness (2g).
6. Implement the small `publish` step plus the daily workflow.

## Open questions for you

1. **Fallback policy:** all-or-nothing publication (Option A), or per-program fallback to
   the previous manifest's file (Option B)?
2. **Scope source of truth:** OK to make the repo constant authoritative, with scope
   changes via PR, and drop the scope-release workflow and `scope_revision`?
3. **Journal:** OK to replace the journal protocol with "CAS write; on unknown outcome,
   re-read; else fail and retry tomorrow"?
4. **Parser strictness:** how much should a BLS layout change break the build? My
   recommendation is to fail only when the columns the catalog needs are missing.
5. **Double download:** OK to download once?
6. **Review tooling:** willing to rewrite the `.roborev.toml` guidelines to weigh
   complexity, and to stop auto-triggering design review on every doc commit?
7. Is there a reason I'm missing for the high-assurance posture, such as an
   institutional requirement at EPI, or other consumers with stronger needs than
   `find_bls()`?
