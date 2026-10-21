# Notes for agents working in this repository

`bls_index` builds a catalog of BLS series IDs and titles from the BLS flat files, and
publishes it weekly as a GitHub Release. Read these first:

| File | What it is |
|---|---|
| [`README.md`](README.md) | What the catalog is, how to use, build and publish it |
| [`design.md`](design.md) | The contract. Its Non-goals, Accepted risks and Decisions are settled: do not reopen them without a new argument |
| [`plans/`](plans/) | The newest dated file is the current plan, with next steps |
| [`docs/`](docs/) | Reference: schema, survey names and aliases, synthesized-title rules |
| [`docs/evidence/`](docs/evidence/) | Dated measurements and test results; records, not instructions |
| [`research/`](research/) | The original survey of existing BLS catalogs |

## Working here

- **Tests:** `./scripts/check.sh` runs the offline suite. It needs no network access
  and no credentials.
- **BLS access:** real downloads need `BLS_INDEX_USER_AGENT` set. It is a repository
  secret, and locally an environment variable. A full build downloads 1.66 GB from BLS
  at one request per second, so don't run one without a reason.
- **R client checks:** `uv run python scripts/fixture_catalog.py DIR`, then
  `Rscript examples/check_find_bls.R DIR`. They need the R packages listed in the README.
- **Changes:** make each change on a branch and open a pull request. `main` is protected:
  merging needs a pull request and the CI `check` job. The maintainer merges, with
  `gh pr merge N --merge`. Ask them when a PR is ready.
- **Design first:** a change in behavior (search rules, publication, catalog columns)
  goes into `design.md` first, then the code.
- **Plans:** new plans go in `plans/YEAR-MM-DD-short-description.md`.
- **Scratch files:** use `tmp/`, which git ignores. Never commit raw BLS files or
  credentials.

## Reviews (roborev)

- A post-commit hook sends every commit to one code reviewer automatically. See the
  results with `roborev list` and `roborev show <job>`.
- At milestones, run
  `roborev review --branch --base main --panel checkpoint_panel --wait`. That panel
  covers code, design and security.
- `.roborev.toml` tells reviewers to weigh findings against the project's low stakes.
  Fix real findings. For a finding that needs several unusual conditions at once, record
  it as an accepted risk in `design.md` rather than adding code, then close the job with
  `roborev comment <job> "..."` and `roborev close <job>`.

## Publishing

- **The schedule publishes on its own** (`.github/workflows/daily.yml`).
- **Manual runs:**
  - `-f publish=none` only builds
  - `-f publish=test` makes a prerelease that never becomes "latest"; the next run
    deletes it
  - `-f publish=force` writes a public release. Ask the maintainer before forcing one.
- **The write token** exists only in the `publish` job and `scripts/publish.sh`. Changes
  there get a security review (the `checkpoint_panel`).
- **Secrets:** `HEALTHCHECKS_URL` is a secret ping URL. Never ask for it or print it.

## Style

- **Prose:** short sentences, and no em dashes.
- **R code in `examples/`:** use `<-` for assignment.
