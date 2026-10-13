# Phase 1 full-33 runner benchmark

GitHub run: https://github.com/Economic/bls-index/actions/runs/38396407578

Revision: `a871ee0dae94405172eba8d46d7fe1c397e225e5` on `feature/phase1-native-builders`.
Manual `dry-build` workflow, Ubuntu 24.04 GitHub-hosted runner; no R2 credentials or publication. Only diagnostic JSON artifacts were uploaded. The first dispatch failed workflow parsing because `runner.temp` was unavailable in job-level env; this revision fixes that expression and the recorded dispatch succeeded.

Authoritative diagnostics: [full report](2026-10-13-full33-dry-build.json), [runner info](2026-10-13-full33-runner-info.json). Earlier partial-source records remain historical evidence, not rewritten success claims.

## Observed results

- All 33 initial programs freshly downloaded and independently built, 8,315,248 combined rows. No global ID collision, schema or dictionary failure.
- 51 source inputs, 102 HTTP requests, no request or input-set retries. Unique source bytes 1,659,175,038; received HTTP body bytes 3,318,350,076 including 1,659,175,038 verification bytes. These are application-body counts, not total wire traffic.
- Combined Parquet 47,116,278 bytes, SHA-256 `a3aab57b5afbd28f8235cce9ef32b7ac55a2ce56aef78b239196ef916098e2b0`.
- Download 104.75 s; program builds 148.53 s; combined validation/write 12.51 s; total command 268.58 s. Complete job 4m44s.
- Actual pinned dictionary commands all passed: spec 0.018 s, metadata 0.017 s, data 8.098 s.
- 4 CPUs, 16,766,414,848 bytes physical memory. Python lifetime peak RSS 4,615,942,144 bytes. Child maximum RSS also reports 4,615,942,144 bytes; it is not an independent concurrent memory total and must not be summed with self. Fork inheritance can influence child high-water measurements.
- Sampled peak run-directory bytes 2,731,014,644. Lowest sampled filesystem free bytes 86,661,804,032. Sampling interval 0.25 s; brief transient disk peaks may be missed.
- Combined Parquet load 0.317 s; unemployment restricted to `ln`/`NSA`: 7,084 matches in 0.125 s; registered nurses restricted to `oe`/`NSA`: 12,644 matches in 0.142 s. Queries are in-memory after load, not browser measurements.

## Derived storage/read estimates (not production measurements)

All per-program Parquets total 47,045,795 bytes. One combined-plus-program set is 94,162,073 bytes (~94.2 MB decimal); two wholly distinct current/previous sets would be 188,324,146 bytes (~188.3 MB), excluding tiny manifests/provenance/journal and staging/unreferenced objects. Content reuse could reduce this. Rollback storage depends on the existing retention/cleanup design; this is not an estimate of unlimited daily retention.

One full catalog read transfers ~47.1 MB; 1,000 full uncached reads ~47.1 GB, and 10,000 ~471.2 GB. Cached or range reads may differ. No dollar estimate is asserted: provider rates, request counts and client caching require separate assumptions. These results measure neither custom-domain delivery nor browser/client cold-read RAM.

## Architecture and remaining decisions

A sequential builder with one compressed combined file is feasible on this intended runner for the measured initial scope; no streaming or concurrent parser rewrite is required for Phase 1. OE dominates program builds (96.03 s), followed by SM (17.81 s); optimization is optional rather than a completion blocker. This single successful run demonstrates feasibility, not a reliability distribution or a maximum-resource guarantee.

Publication, fallback, manifest transitions, rollback, delivery checks, and daily count-change alerts remain later work. Row counts alone must not prove liveness. An operator-approved count-change policy should flag unusual changes without treating valid disappearance as parser failure; no policy is silently chosen here.
