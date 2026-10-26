# Status and next steps (2026-10-26)

This is the current plan. It supersedes `2026-10-21-next-steps.md`.
[`design.md`](../design.md) is the contract. The earlier
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
  `epidatatools::find_bls()`. The original full-catalog measurement was 1.0–1.6 s
  ([evidence](../docs/evidence/2026-10-21-find-bls-reference-client.md)). The reference
  client now follows the stemming and cache fixes merged in
  [epidatatools#29](https://github.com/Economic/epidatatools/pull/29). Its 49 offline
  checks pass on the 111-row fixture catalog.
- **First release:** `catalog-2026-10-21T0934Z`, from the scheduled run on 2026-10-21.
  All six checks of step 1 passed
  ([evidence](../docs/evidence/2026-10-21-first-release.md)).
- **Runbook:** [`docs/runbook.md`](../docs/runbook.md), signed off by the maintainer on
  2026-10-24.

## 1. Verify the first real release: done

All six checks passed on 2026-10-21
([evidence](../docs/evidence/2026-10-21-first-release.md)).

## 2. Finish the launch

1. **Runbook: done.** The maintainer signed off on `docs/runbook.md` on 2026-10-24. It
   covers the design's "Done when" item 6.
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
   "Using the catalog" section) and that the client has merged in `epidatatools`.

## 3. Client port and reference parity: done

[Economic/epidatatools#29](https://github.com/Economic/epidatatools/pull/29) merged on
2026-10-26. It replaces the retired Data Finder client with the catalog client,
including its dependencies, documentation and testthat checks.

[Issue #24](https://github.com/Economic/bls-index/issues/24) identified differences
introduced during that port. The reference client and `design.md` now adopt them:

- Join singulars and plurals ending in "y" and "ies", with whole-word boundaries for
  short roots. "Industries" finds "industry", and "city" and "cities" match each other
  without matching "citizen".
- Recover from damaged state files, write state through a temporary file and rename,
  and keep searches working when state cannot be written.
- Keep the old catalog if the new catalog cannot be renamed into place.
- Prefer the manifest URL option over the environment variable, and treat an empty
  environment variable as unset.
- Check scalar arguments and seasonality before reading the catalog. Require a whole
  number of at least 1, or `Inf`, for `limit`.

The offline R checks cover these regressions. Future search behavior changes still
start in `design.md`, then update both clients.

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
