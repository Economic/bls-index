# Phase 1 runner build and client search measurements (2026-10-20)

## Runner build

[Run 39370552340](https://github.com/Economic/bls-index/actions/runs/39370552340): the
manual `build` workflow on `main` at `992e3b6`, on a 4-CPU Ubuntu 24.04 GitHub-hosted
runner, building all 33 programs.

| | Phase 1 code | Before (2026-10-13, run 38396407578) |
|---|---|---|
| Job time | 1 m 33 s | 4 m 44 s |
| Command time | 77 s | 269 s |
| Download | 56 s, 48 files, 1.66 GB, each downloaded once | 105 s, 102 requests, 3.32 GB |
| Program builds | 7 s | 149 s |
| Combine and data-dict checks | 14 s | 13 s |
| Peak RSS (`/usr/bin/time`) | 4.7 GB | 4.6 GB |
| Catalog | 8,315,248 rows, 47,208,957 bytes | 8,315,248 rows, 47,116,278 bytes |

The run's catalog SHA-256 (`1ad9cd6a…`) equals a local build of the same day's sources,
which in turn matched the pre-Phase 1 code's output row for row (`scripts/golden.py`).
No builder warnings.

## Searching the catalog from R

Measured locally with R 4.5.3, `arrow`, and `duckdb` on the same 8.3-million-row catalog.

| Approach | Time per search | Memory |
|---|---|---|
| `arrow::read_parquet` into a data frame, then `grepl(ignore.case = TRUE)` | 14–29 s | 2.2–2.3 GB data frame, about 5 GB peak |
| Same, but lowercase titles once (32 s), then `grepl(fixed = TRUE)` | 0.5 s | as above |
| `arrow::open_dataset` with `match_substring(ignore_case = TRUE)` on the file | 0.3–0.5 s | about 1 GB peak |
| `duckdb` `ILIKE` query on the file | 0.8 s | small |

OE has 6.0 million of the 8.3 million rows. Without it, the data frame is 470 MB.
Loading the whole catalog into an R data frame is too slow and too large for an
interactive `find_bls()`. Querying the Parquet file in place is fast.
