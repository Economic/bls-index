# First real release (2026-10-21)

Plan step 1: checks of the first scheduled publish, run at 13:11 UTC on 2026-10-21.

## The run

[39578022738](https://github.com/Economic/bls-index/actions/runs/39578022738) was the
first scheduled run of the `daily` workflow. It was set for 09:23 UTC and started at
09:34 UTC. GitHub often starts scheduled runs late. It took 4 min 36 s. The build,
publish and monitor jobs all succeeded.

## The releases

`gh release list` showed one release, `catalog-2026-10-21T0934Z`, marked latest. The
test prerelease `test-2026-10-21T0404Z` was gone, deleted by the publish's cleanup.

## The manifest

`curl -L https://github.com/Economic/bls-index/releases/latest/download/latest.json`
worked without credentials. It listed:

- `tag`: `catalog-2026-10-21T0934Z`
- `built_at`: 2026-10-21T09:34:41Z; `published_at`: 2026-10-21T09:38:36Z
- `git_revision`: `017b291`, the head of `main`
- `catalog.url`: the tag-specific URL for the same tag
- `catalog.rows`: 8,315,248; `catalog.bytes`: 32,939,145
- all 33 programs

The row count and size match the test releases.

## The client

`examples/find_bls.R`, with its default manifest URL and an empty cache
(`options(bls_index.cache_dir = tempfile())`), downloaded and verified the catalog. Then
`find_bls("unemployment rate", survey = "ln")` found 4,197 matches and listed
`LNS14000000`, "(Seas) Unemployment Rate", first. The first call took 2.4 s in total,
including the download, on the maintainer's workstation.

## Not checked here

- **The monitor:** the maintainer confirms the success ping, and that the check's period
  and grace time are back to 1 day each.
