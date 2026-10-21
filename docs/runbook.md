# Runbook

How to operate the weekly catalog. [`design.md`](../design.md) explains why it works
this way. Every command runs from a clone of the repository, with `gh` logged in as a
user who can write to it.

## Manual runs

All manual runs use the `daily` workflow. Run them from `main`, except the full build
that tests a new program (see "Adding a program").

| Goal | Command |
|---|---|
| Rerun the build, without publishing | `gh workflow run daily.yml -f publish=none` |
| Build a few programs, as a diagnostic | `gh workflow run daily.yml -f publish=none -f programs=ap,pr` |
| Publish a test prerelease | `gh workflow run daily.yml -f publish=test` |
| Publish a real release now | `gh workflow run daily.yml -f publish=force` |
| Publish only if one is due | `gh workflow run daily.yml` |

- **Watch a run** with `gh run watch`, or list runs with
  `gh run list --workflow daily.yml`.
- **A test prerelease** never becomes "latest", so clients never see it. The next run
  that publishes deletes it.
- **A forced publish** writes a public release that clients download. Ask the
  maintainer first.
- **A subset build** never publishes, and it does not report to the monitor.
- **A full manual build reports to the monitor,** like a scheduled one. If it fails, the
  monitor emails.

## When a run fails

1. Open the run: `gh run view <run id>`. The failed step's log usually names the
   problem.
2. Download the diagnostic report:
   `gh run download <run id> -n report-<run id> -D tmp/report`. Its `report.json` names
   the failing program and stage. The artifact is kept for 7 days.
3. A failed run leaves the latest release unchanged. Clients keep using it.
4. A real failure is usually a BLS format change in one program. Fix it in a pull
   request.
5. Once the fix is merged, the next daily run publishes if a release is due. To publish
   sooner, ask the maintainer about a forced publish.

A one-off failure, such as a BLS timeout, needs no fix. The next day's run tries again.

## Rollback

To send clients back to an older catalog:

```sh
gh release list                       # find the release to restore
gh workflow disable daily.yml         # hold the rollback
gh release edit <older tag> --latest  # clients now get the older catalog
```

- **Disable the workflow first.** The older release is at least 6 days old, so without
  that, the next daily run publishes a new release and undoes the rollback.
- **Only retained releases can be restored.** Each publish keeps the newest 12, about
  three months.
- **The bad release can stay.** Clients follow "latest", not the newest tag. To remove it
  anyway, run `gh release delete <bad tag> --cleanup-tag`.

When the fix is merged:

```sh
gh workflow enable daily.yml
gh workflow run daily.yml -f publish=force   # ask the maintainer first
```

## Alerts

One healthchecks.io check emails the maintainer. GitHub's own emails about failed runs
are a bonus.

| Email | Meaning | What to do |
|---|---|---|
| Down, soon after a run | A full run failed: the build failed, or the publish did | See "When a run fails" |
| Down, with no run failing | No successful run for about 48 hours | See below |
| Up | A run succeeded after an alert | Nothing |

When no successful run has happened:

1. Check `gh run list --workflow daily.yml`. If no runs are scheduled, GitHub may have
   disabled the schedule. See below.
2. If runs started but never finished, look for a stuck or cancelled run, or a GitHub
   Actions outage.
3. Start a run by hand with `gh workflow run daily.yml -f publish=none`. Its success ping
   brings the check back up.

The ping URL is the `HEALTHCHECKS_URL` repository secret. It is private, so never print
it.

## The 60-day schedule limit

GitHub disables a public repository's scheduled workflows after 60 days without
repository activity. The missed-run alert is the warning. To turn the schedule back on:

```sh
gh workflow enable daily.yml
```

Any commit to the repository also resets the 60 days.

## Adding a program

Each program is one pull request. The [Scope](../design.md#scope) section of the design
is the rule. The pull request:

1. **Scope and builder:** in `src/bls_index/scope.py`, add the program code to
   `NATIVE_TITLE_PROGRAMS` or `SYNTHESIZED_TITLE_PROGRAMS`. A native-title program needs
   nothing more: the shared parser reads its `.series` file. A synthesized-title program
   also needs its lookup files in `LOOKUP_FILES` and a `SYNTHESES` entry in
   `src/bls_index/builders.py`. Document its templates in
   [`synthesized-source-contracts.md`](synthesized-source-contracts.md).
2. **Names:** the program's survey name in `SURVEY_NAMES`, and any aliases in
   `SURVEY_ALIASES`. Record the source in [`survey-names.md`](survey-names.md).
3. **Dictionary:** the program code in the `program` values in `data-dict.yaml`. For a
   synthesized-title program, also add it to the list in the `title_source` rule.
4. **Tests:** builder tests with small fixtures. `./scripts/check.sh` must pass.
5. **A full build:** before merging, build all programs once, on the branch:

   ```sh
   gh workflow run daily.yml --ref <branch> -f publish=none
   ```

   A full build downloads 1.66 GB from BLS. The `report.json` artifact shows the new
   program's rows.

The next weekly release then includes the program.

## Costs

None are expected:

- **GitHub Actions:** free for public repositories on standard runners. A run takes
  about 5 minutes.
- **Releases:** free storage. Each holds about 33 MB, and 12 are kept.
- **healthchecks.io:** the free tier.
