# Outstanding Gate 1 checks

> **Historical (2026-10-13).** Superseded by the rewritten [`design.md`](../../design.md) and [`plans/2026-10-13-simplification-implementation.md`](../../plans/2026-10-13-simplification-implementation.md). Gate 1 is closed by decision; remote read-back timing moves to the Phase 2 staging run.

The successful full-33 dry build is not a declaration that Gate 1 is closed.

1. **Immutable-object read-back/checksum timing:** the local build checks bundle checksums, but the recorded runner report does not time remote immutable-object upload/read-back. No production write is authorized by Phase 1. Any staging measurement must use the separately scoped private staging gate and record storage/read latency; otherwise this acceptance check remains pending before publication integration.
2. **Actions usage:** measured complete job 4m44s implies approximately 142 runner-minutes for 30 similar daily runs, or 147 minutes for 31 runs, excluding CI, retries and other workflows. The repository is public and uses a standard GitHub-hosted runner; recorded operator information says these minutes are free. Artifact retention is diagnostic-only, seven days, and shares organization storage allowances (recorded Team allowance 2 GB); organization aggregate usage/budgets have not been inspected. This arithmetic is not a billing audit or a storage quota guarantee.
3. **Count-change policy — resolved 2026-10-13:** the operator approved retaining diagnostic row counts without automated thresholds, persistent warnings, acknowledgment state, or GitHub issue tracking. Structural failure and empty-program rejection remain implemented; valid series disappearance is not itself parser failure. A future diagnostic comparison of IDs added/removed and titles changed is deferred and is not a Gate 1 prerequisite. This decision accepts the risk that a consistently incomplete but structurally valid source can pass.

These are named prerequisites rather than silently completed checks. The current implementation and full-data results can be reviewed independently of those pending policy/publication measurements.
