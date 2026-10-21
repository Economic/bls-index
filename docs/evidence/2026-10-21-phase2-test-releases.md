# Phase 2 test releases and monitor (2026-10-21)

Plan task 2.5: the `daily` workflow on GitHub, before the first real release.

## Test publishes

| Run | Inputs | Build job | Publish job | Result |
|---|---|---|---|---|
| [39541461860](https://github.com/Economic/bls-index/actions/runs/39541461860) | `publish: test` | 4 min 52 s | 12 s | Prerelease `test-2026-10-21T0358Z`, not marked latest |
| [39542000212](https://github.com/Economic/bls-index/actions/runs/39542000212) | `publish: test` | 3 min 15 s | 13 s | The first test release and its tag were deleted; prerelease `test-2026-10-21T0404Z` replaced it |

The first test release's manifest listed 8,315,248 rows and a 32,939,145-byte catalog.
The `pre-cleanup` tag was untouched by the cleanup.

The reference client (`examples/find_bls.R`), pointed at the first test release's
`latest.json`, downloaded the catalog from its tag-specific URL, verified the checksum,
and searched it in 4.6 s total. "unemployment rate" in `ln`, seasonally adjusted, listed
`LNS14000000` first.

## Monitor

- **Pings:** healthchecks.io recorded a start ping and a success ping for each run, from
  GitHub runner addresses. Its timings matched the runs: 5 min 6 s and 3 min 31 s.
- **Alerts:**
  - With the check's period and grace time shortened to 1 minute, the check went down,
    but no email arrived. The cause is unknown.
  - The integration's test notification arrived.
  - A success ping, then a `/fail` ping, sent by hand (the ping the workflow sends on
    failure), produced alert emails as expected.
- **Not run:** a forced-failure workflow run. The `/fail` path was confirmed by hand
  instead, so the monitor job's failure branch has not yet run on GitHub.

## Branch protection

Ruleset `protect main` is active on `main`. It restricts deletion, blocks force pushes,
requires a pull request before merging (0 approvals), and requires the CI `check` status
check. Its bypass list could not be read without admin rights; it was set up empty.
