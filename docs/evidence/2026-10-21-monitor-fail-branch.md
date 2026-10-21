# The monitor job's failure branch on GitHub (2026-10-21)

The last monitor gap: the `daily` workflow's monitor job had never taken its `/fail`
branch on GitHub. The ping and its email had only been confirmed by hand.

## The test

A manual full run, [39616240038](https://github.com/Economic/bls-index/actions/runs/39616240038),
dispatched with `publish: none` and then cancelled.

- **The build job** started at 14:22:09 UTC and sent the start ping. Healthchecks.io
  recorded it.
- **The cancel** arrived at about 14:25:37 UTC. The publish job, still waiting, was
  cancelled. The build job's steps had all finished, but GitHub recorded the job itself
  as cancelled.
- **The monitor job** ran anyway, because of `if: always()`. Its log shows
  `BUILD: cancelled` and `PUBLISH: cancelled`, so it took the `/fail` branch.
- **Healthchecks.io** marked the check down, and the alert email arrived.
- **Afterwards** the maintainer sent a success ping by hand, and the check came back up.

Nothing was published, and the latest release stayed `catalog-2026-10-21T0934Z`.

## A slip in the test

The plan was to cancel during setup, before the build step downloads anything. The
script waited for the start-ping step to show as finished. But `gh run view` lists no
steps while a job is running, so the wait ran out after about 3 minutes, and the script
cancelled anyway. By then the build had finished, so the run downloaded the full 1.66
GB from BLS, at the usual one request per second. The runbook now says to cancel as
soon as the run appears.

## Result

The monitor's failure branch, the `HEALTHCHECKS_URL` secret in that job, and the `/fail`
ping all work on GitHub. A real build or publish failure takes the same branch.
