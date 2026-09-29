# Plan: build and publish a current BLS series catalog

## Purpose and boundary

This is a **standalone `bls_index` project**. Build a reproducible, current, downloadable index of BLS series IDs and searchable titles from the official flat files at `https://download.bls.gov/pub/time.series/`. Do not implement or change `epidatatools` here. A future `epidatatools::find_bls()` may download the published file into a user cache and search it locally; the index must therefore have a documented, stable file format and discovery mechanism. No hosted query API, browser UI, SQLite-over-HTTP, or DuckDB remote range-read requirement for v1.

“Current” means **present in the latest successfully ingested BLS `.series` files**, not necessarily still receiving observations. Frozen but still published series belong in the catalog; series removed from BLS files do not. Record source freshness explicitly, and never describe a failed or outdated build as a fresh snapshot. The research note `research/2026-08-11-existing-bls-series-catalogs.md` is the starting inventory, not a substitute for validating current BLS files.

## Deliverable and contract

- Publish one canonical, compressed `bls_index.parquet` per successful refresh (served at an immutable `bls_index-<checksum>.parquet` URL). Start with a flat search schema: `program`, `series_id`, `series_title`, `title_source` (`native`/`synthesized`), `seasonal` (SA/NSA/unknown), `begin_year`, `end_year`, and an explicitly defined `status` (live/frozen/unknown). Include `survey_name` and periods if verified and useful; nullable values must stay nullable rather than be guessed. Specify types, normalization, and schema version in documentation. Keep IDs as strings, trim BLS padding, and preserve the original BLS title when supplied. Do not treat BLS survey/program codes as interchangeable without an explicit mapping.
- Maintain a repository-root `data-dict.yaml` (the documented data-dict naming convention) with `name: bls_index` and a Parquet source pointing to the local `bls_index.parquet`. Define column meanings and types, nullable fields, allowed categorical values, and machine-checkable constraints (including required IDs/titles and uniqueness where verified). Pin the `data-dict` CLI version; run `validate-spec`, `validate-meta`, and `validate-data` on every publication candidate in CI. The dictionary's `$version` identifies the data-dict specification, separately from this catalog's own schema version. Measure full-data validation cost and keep nonexpressible BLS-specific checks in the build tests. Keep the authoritative dictionary in the repository; if also publishing it beside the artifact, arrange a stable source path (or generate a publication copy pointing to the immutable artifact) and validate that copy. Runtime clients do not need the CLI.
- Publish a small `latest.json` containing at least schema version, artifact URL, SHA-256, byte size, build timestamp (UTC), per-program source timestamps or identifiers, coverage counts, and the freshness/validation outcome. A stable manifest URL points to a **content-addressed** Parquet filename; the catalog file at that filename never changes. The manifest is updated only after artifact upload and validation.
- Keep only the current artifact plus a short-lived predecessor during cache propagation or rollback. Delete obsolete artifacts after the grace window; this is not a historical archive. The manifest remains pointed at the last valid catalog if a build fails.
- Provide a documented build command, pinned dependencies, fixtures, automated tests, validation report, and an operational runbook (credentials, manual rebuild, rollback, alerting, and expected costs). Never commit R2 credentials or raw BLS bulk files.

The research scoped 54 programs and about 9.48 million series: 30 programs with native titles in full; 24 without native titles requiring title synthesis; exclude `nw` and the ten case-characteristics tier-3 programs initially. Re-check the directory list and counts at build time. The estimate of ~50 MB for a compact Parquet file is **not a measured v1 deliverable**: measure final bytes, download time, and local query performance before settling the schema and refresh cadence.

## Work sequence

### 1. Establish the reproducible ingest

- Choose a maintainable build language and pin a runtime plus dependencies; keep the pipeline independent of the `epidatatools` package. Document one local build invocation used unchanged in CI.
- Inventory in-scope BLS `.series` files and the lookup files needed for untitled programs. Fetch via HTTPS with a descriptive, contactable User-Agent, bounded concurrency, retries with backoff, and sensible timeouts. Honor `ETag`/`Last-Modified` when useful; do not assume byte-range support or compression on BLS downloads. Download to temporary files and verify full responses before parsing.
- Normalize per-program schemas explicitly; fail on unexpected layouts instead of silently shifting fields. Cover anomalies recorded in the research (`cc` concatenated header/row; extra trailing fields in `eb`, `ec`, `ee`, `gp`, `hs`, `pd`, `sa`, `sh`, `si`; `hs` shifted year columns; `kv` without year fields). Trim padded IDs and validate that IDs and decoded dimensions are plausible. Keep provenance for every row.
- Implement an initial build for the 30 native-title programs, including `oe`. Validate it independently before expanding scope. Add program-specific title templates and lookup joins for the 24 tier-2 programs, prioritizing live `sm`, `jt`, and `pr`. Label synthesized titles, check join cardinality and missing labels, and test each program with representative known series. Do not publish a partial build as full coverage.

### 2. Define and test the catalog semantics

- Set documented rules for seasonal adjustment, missing metadata, and `status`; do not infer universal liveness solely from `end_year` without checking program quirks. Preserve frozen, still-listed series. No first-seen/last-seen state store is required for v1; disappearance from a current BLS source removes an ID in the next valid snapshot.
- Enforce uniqueness of `series_id` (or document and test any genuine cross-program collision), nonempty titles, valid program assignments, sensible years, and predictable nulls. Reject unexpected row-count drops, program omissions, title-join explosions, malformed text, or missing required columns; thresholds should be explicit and require investigation rather than masking genuine BLS changes.
- Compare representative IDs against BLS files and, where feasible, the BLS data API: common unemployment/CPS, CES, CPI, JOLTS, and OEWS cases; include frozen and deleted-ID cases. Verify that previously published content is left untouched when inputs or validation fail.
- Benchmark search on a downloaded local file for realistic queries, including `unemployment` and an OEWS occupation, with a survey restriction and seasonality filter. Document that free-text search semantics and relevance ranking belong to consuming clients unless a common search specification is deliberately added later. Avoid claiming subsecond searches or a particular artifact size until measured.

### 3. Automate builds without operating a server

- Use a **scheduled GitHub Actions workflow** in a public `bls_index` repository on a standard Linux runner, plus manual dispatch. Test that actual memory, disk, runtime, BLS network access, and dependency setup fit runner limits; the research's few-minute full rebuild is an estimate. If public hosting is unsuitable, measure private-repo minute usage before considering a self-hosted runner. Cloudflare Workers Cron is not the bulk build environment.
- Build a candidate, run the pinned `data-dict` CLI's `validate-spec`, `validate-meta`, and `validate-data` plus BLS-specific schema, coverage, and provenance checks; calculate SHA-256 and sizes, and produce a machine-readable validation summary. If inputs have not changed, skip publishing; still report source-check results. Upload with a narrowly scoped R2 write token from CI secrets. Read back and verify the candidate object, then atomically switch `latest.json` last. On any failure, alert maintainers and retain the previous valid manifest and artifact. Support a manual rollback by repointing the manifest during the grace period.
- Report build age and source ages; add a failure/staleness notification so a quietly stopped daily job is visible. Specify how to handle upstream outages and how often truly frozen datasets need rechecking; avoid permanent blind trust in a one-time download.

### 4. Serve safely and cheaply

- Store the Parquet and manifest in an R2 **Standard** bucket exposed through a dedicated Cloudflare custom domain; turn off the public `r2.dev` URL so security/cache rules cannot be bypassed through it. No API keys for read access; downloads must work from non-browser tools such as R and `curl` without JavaScript challenges.
- Configure a narrow Cache Rule for the immutable `.parquet` paths (not all site traffic), with a long TTL; configure a short TTL for `latest.json` so publication propagates promptly. Check `Cache-Control`, `ETag`, `Content-Length`, and actual cache hit/miss behavior after launch. `.parquet` is not cached by Cloudflare by default. Avoid cookies or arbitrary query strings in published URLs that fragment the cache.
- Add a conservative per-IP, path-scoped WAF rate-limit **block** rule only after measuring legitimate traffic; leave room for shared institutional IPs. Do not use CAPTCHA/Managed Challenge for the machine-readable download. Add usage and budget alerts, understanding that alerts are not hard cost caps. Document that caching and rate limiting mitigate abuse but do not guarantee a maximum bill. Revisit protections using measured R2 Class B reads and edge hit rates.
- Verify cold download, repeated download, checksum validation, manifest refresh, and old-file cleanup from an external machine. Test both fresh and cached requests and a failure/rollback path. Keep the catalog within the chosen CDN's cacheable size limit or revise serving strategy.

## Interface reserved for future `epidatatools` integration

Publish `data-dict.yaml`, schema and manifest examples, a checksum verification example, a small fixture, and the stable manifest URL. The future client can check the manifest at a documented interval, fetch a new file once to `tools::R_user_dir("epidatatools", "cache")`, verify the checksum and supported catalog schema version, check essential columns/types, swap the cache atomically, and search locally/offline afterward. It does not need the `data-dict` CLI or a full-row validation scan at runtime. Expose catalog source and age to callers. This integration, its user-consent/download UX, API compatibility, CRAN checks, and relevance ranking are **out of scope for this repository**; do not make the index build depend on `epidatatools`.

## Done when

1. A clean checkout can reproduce the build and tests locally and in CI without private local data.
2. All 54 in-scope programs are ingested, with documented exclusions, correctly labeled native/synthesized titles, and automated anomaly/uniqueness/coverage checks; a pinned `data-dict` validator passes specification, metadata, and full-data checks on the candidate Parquet; real final size, validation cost, and search benchmarks are recorded.
3. A scheduled refresh publishes only validated changes, keeps the last valid catalog on failure, exposes truthful source/build timestamps, and alerts on prolonged staleness.
4. The HTTPS manifest and Parquet download work without credentials or browser verification; checksum, caching, rollback, cleanup, and a representative client download have been tested.
5. A public schema, freshness policy, operational runbook, and narrowly scoped Cloudflare protections exist; no `epidatatools` source changes are required to consider this project delivered.

## Decisions
<!-- Review findings considered and rejected, with the reason for each. -->
