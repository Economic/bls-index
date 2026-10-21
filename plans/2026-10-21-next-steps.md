# Status and next steps (2026-10-21)

This is the current plan. [`design.md`](../design.md) is the contract. The earlier
implementation plan and its reviews are in git history (tag `pre-cleanup`, and the
commits before this file); everything they decided is reflected in `design.md` and the
code.

## Where things stand

- **Build:** all 33 programs build from the BLS flat files in about 5 minutes on a
  GitHub runner, giving a 33 MB Parquet catalog of 8,315,248 series. On a saved full
  download, the current builders reproduce the original builders' output row for row.
- **Catalog contents:** `survey_name` and `survey_aliases` columns, documented in
  `docs/schema-v1.md` and `docs/survey-names.md`.
- **Publishing:** the `daily` workflow builds every day and publishes a GitHub Release
  when the latest is at least 6 days old. Two test publishes and their cleanup passed on
  GitHub ([evidence](../docs/evidence/2026-10-21-phase2-test-releases.md)).
- **Monitor:** healthchecks.io records each run's start and success pings. Both alerts
  email: a failed run, through the monitor job's `/fail` branch on GitHub
  ([evidence](../docs/evidence/2026-10-21-monitor-fail-branch.md)), and a missed run
  ([evidence](../docs/evidence/2026-10-21-missed-run-alert.md)).
- **Branch protection:** the `protect main` ruleset requires a pull request and the CI
  `check` job.
- **Client:** `examples/find_bls.R` is the reference client for
  `epidatatools::find_bls()`. It searches the full catalog in 1.0–1.6 s, and its 32
  offline checks pass ([evidence](../docs/evidence/2026-10-21-find-bls-reference-client.md)).
- **First release:** `catalog-2026-10-21T0934Z`, from the scheduled run on 2026-10-21.
  All six checks of step 1 passed
  ([evidence](../docs/evidence/2026-10-21-first-release.md)).
- **Runbook:** [`docs/runbook.md`](../docs/runbook.md), a first draft.

## 1. Verify the first real release: done

All six checks passed on 2026-10-21
([evidence](../docs/evidence/2026-10-21-first-release.md)).

## 2. Finish the launch

1. **Runbook.** A first draft of `docs/runbook.md` is written. Check it against this
   list, and against the design's "Done when" item 6:
   - a manual rerun (`gh workflow run daily.yml -f publish=none`)
   - a forced publish (`-f publish=force`)
   - a test release (`-f publish=test`)
   - rollback: `gh release edit <tag> --latest` on an older release, and disabling the
     schedule to hold it until the next fix
   - adding a program: builder, tests, `scope.py`, `SURVEY_NAMES` and `SURVEY_ALIASES`,
     the `data-dict.yaml` program values and, for synthesized titles, the `title_source`
     rule; then a full build before merging
   - what the monitor emails mean
   - re-enabling the schedule if GitHub disables it after 60 days without repository
     activity
   - costs: none expected for a public repository
2. **Verify the missed-run alert on the live check: done.** The alert email arrived
   when the check's deadline passed on its own
   ([evidence](../docs/evidence/2026-10-21-missed-run-alert.md)).
3. **Watch a week.** The design's "Done when" requires 7 consecutive successful daily
   builds and at least two weekly releases. The second release should come from the
   first scheduled run at least 6 days after the first, around 2026-10-27.
4. **Final review.** Run a `checkpoint_panel` review of the launch work, for example
   `roborev review --since <commit> --panel checkpoint_panel --wait`, and check `main`
   against the design's "Done when" list. The panel includes the security reviewer. Fix
   real findings.
5. **Announce,** when the maintainer decides: where the catalog lives (the README's
   "Using the catalog" section) and that the client is coming to `epidatatools`.

## 3. Port the client to epidatatools

This work belongs in the `Economic/epidatatools` repository, not here.

- Replace `find_bls()` with the reference client's behavior:
  - signature `find_bls(search_string, survey = NULL, seasonality = NULL, limit = 1000,
    titles_only = FALSE, refresh = FALSE)`
  - a deliberate breaking change: `max_results` and `metadata` are gone
  - always returns `series_id`, `series_title`, `program`, `survey_name`, `seasonal`,
    `begin_year`, `end_year` and `end_period`
- Add `arrow`, `SnowballC`, `openssl` and `jsonlite` as dependencies, if not already.
- Turn the 32 checks in `examples/check_find_bls.R` into `testthat` tests, using a small
  fixture catalog. `scripts/fixture_catalog.py` here builds one.
- Document the weekly cache, `refresh = TRUE`, and the `bls_index.manifest_url` option.
- Follow `epidatatools`'s own conventions: it currently uses `=` for assignment, while
  this repository's examples use `<-`.

## 4. Backlog (only when wanted)

- **The 21 deferred programs,** which `design.md` lists: frozen twins (`ee`, `sa`, `mu`,
  `mw`, `pd`, `cc`, `ec`, `nc`, `eb`, `jl`), injuries and illnesses (`ii`, `sh`, `hs`,
  `si`), and standalone frozen programs (`ml`, `gp`, `in`, `gg`, `bp`, `li`, `bg`). Each
  is a pull request, as in the runbook.
- **Deferred search features:** quoted phrases, and "did you mean" suggestions.
- **Deferred column:** `begin_period`.
- **Operator cleanup:** delete the unused Cloudflare R2 buckets `bls-index` and
  `bls-index-staging` and their API token.

## Known gaps

- **GitHub disables the schedule after 60 days without repository activity.** The
  monitor's missed-run alert is the warning; re-enable the workflow or make any commit.
