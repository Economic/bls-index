# Catalog schema v1

Schema version 1 is the canonical row format for series records. Local native-title parsing
is implemented for all 30 fixed native-title programs. Bounded local synthesized-title parsers
are implemented for `pr`, `sm`, and `jt`. The combined-candidate validator checks explicit frames
against schema-v1 and BLS-specific invariants; its local writer stages a candidate and runs the
pinned data-dictionary checks. Neither function downloads source data or publishes anything.

## Columns

| Column | Type | Null? | Meaning and normalization |
|---|---|---:|---|
| `program` | string | no | The explicit BLS flat-file directory/program code passed to the builder. It is not inferred from the series ID. |
| `series_id` | string | no | BLS series identifier with source padding removed from both ends. IDs remain strings and must be nonempty and unique within a program; native builders apply their documented source checks. |
| `series_title` | string | no | Native builders preserve the source title, including surrounding spaces. PR, SM, and JT use synthesized titles from trimmed lookup labels. A title containing only whitespace is invalid. Titles need not be unique. |
| `title_source` | string | no | `native` for native-title programs; `synthesized` for bounded local PR, SM, and JT parsers. |
| `seasonal` | string | no | `SA`, `NSA`, or `unknown`. Observed source code `S` maps to `SA`; `U` maps to `NSA`. A source with no seasonal field (such as `ap`) maps to `unknown`. |
| `begin_year` | int32 | yes | Four-digit year from the source (`1000`–`9999`), or null when the source field is blank. Descriptive metadata only, not a claim of current activity. |
| `end_year` | int32 | yes | Four-digit year from the source (`1000`–`9999`), or null when the source field is blank. Descriptive metadata only, not a claim of current activity. |
| `end_period` | string | yes | Trimmed source end-period code, or null when blank. Kept as the source code; no date is inferred. |

The canonical column order is exactly the table order. The schema version is separate from
any data-dictionary specification version.

## Native source contracts implemented here

All 30 native-title adapters require program-specific ordered headers observed by the
2026-10-07 local source probe. Five representative contracts are listed below; the complete
contract is maintained in `src/bls_index/native_builders.py` and described in
[`native-source-contracts.md`](native-source-contracts.md):

- `ap`: `series_id, area_code, item_code, series_title, footnote_codes, begin_year, begin_period, end_year, end_period`
- `ce`: `series_id, supersector_code, industry_code, data_type_code, seasonal, series_title, footnote_codes, begin_year, begin_period, end_year, end_period`
- `cu`: `series_id, area_code, item_code, seasonal, periodicity_code, base_code, base_period, series_title, footnote_codes, begin_year, begin_period, end_year, end_period`
- `ln`: `series_id, lfst_code, periodicity_code, series_title, absn_code, activity_code, ages_code, cert_code, class_code, duration_code, education_code, entr_code, expr_code, hheader_code, hour_code, indy_code, jdes_code, look_code, mari_code, mjhs_code, occupation_code, orig_code, pcts_code, race_code, rjnw_code, rnlf_code, rwns_code, seek_code, sexs_code, tdat_code, vets_code, wkst_code, born_code, chld_code, disa_code, seasonal, tlwk_code, footnote_codes, begin_year, begin_period, end_year, end_period`
- `oe`: `series_id, seasonal, areatype_code, industry_code, occupation_code, datatype_code, state_code, area_code, sector_code, series_title, footnote_codes, begin_year, begin_period, end_year, end_period`

Padding around header names is accepted because observed BLS headers contain right-padding
before tabs. Data rows must have exactly the header's tab-separated field count. UTF-8 is
strict (no lossy replacement), blank lines and empty data rows are rejected, and control
characters in fields are rejected. The parser retains source row order.

Native IDs are checked against the explicit program-specific ownership prefix, character
and length contract, and any verified source-field component checks. The parser never infers
a program from an ID or assigns a survey name from a guessed prefix. The PR synthesized
parser separately enforces the observed `PR` ownership prefix and seasonal character without
claiming a complete component grammar.

## Validation behavior and deferred verification

Blank begin/end years and end periods become null. Present years must be in the four-digit
range `1000`–`9999`, and a non-null begin year cannot exceed a non-null end year. Present periods must
be a two-digit source token in a recognized monthly (`M`), quarterly (`Q`), or annual (`A`)
family with a positive ordinal; the implementation currently accepts `M01`–`M13`, `Q01`–
`Q05`, and `A01`. A period without an end year is rejected. These are syntax/range checks,
not a claim that every program uses every allowed code.

For programs with a verified seasonal field, the combined-candidate validator enforces the
per-program source mapping in `native_builders.py`: `S` maps to `SA`, `U` maps to `NSA`, and
only mapped values are accepted (`kv` and `cx` are U-only). `ap` and `mp` have no verified
seasonal values and must use `unknown`; `sm`, `jt`, and `pr` accept `SA` or `NSA`. A known
`SA`/`NSA` value must agree with the ID's third character (`S`/`U`). The local probe fixture
for `pr.seasonal` records `S = Seasonal Adjusted` and `U = Not Seasonally Adjusted`.

**Deferred verification before production catalog assembly:** review the source-specific
metadata value domains (including all valid periods, exceptional years, and seasonal values)
against current `.series` inputs for all supported native-title programs and authoritative BLS
code tables; confirm whether any supported program has legitimate values outside the bounded
checks above. The parsers and local build layer do not download sources. Separately, completed
PR source validation is recorded in
[`evidence/2026-10-13-pr-validation.json`](evidence/2026-10-13-pr-validation.json): six PR
source files were downloaded and parsed, their hashes matched on recheck, and validation
completed with status `ok` for 282 rows. This PR-specific check does not resolve the deferred
all-program native source-domain review. The combined-candidate validator checks for duplicate
`series_id` values across its complete requested frame scope (including duplicates within a
program); the local writer stages one canonical Parquet file and runs the pinned `data-dict`
`validate-spec`, `validate-meta`, and `validate-data` commands before exposing the output with a
no-overwrite local operation. These checks are not a production catalog build or publication
integration. The checked-in all-33 small-fixture test exercises this path, but does not fulfill the
planned fresh full-33 dry build and intended-runner benchmark; those Gate 1 measurements remain
pending per [`implementation-plan-v1.md`](plans/implementation-plan-v1.md). Do not infer liveness
from year or period fields. `survey_name` and `begin_period` are intentionally deferred
from schema v1 until their normalization and verification are explicitly approved.

## Bounded synthesized builders

The local PR, SM, and JT parsers and their explicit lookup, title, ID, and evidence limits are
documented in [`synthesized-source-contracts.md`](synthesized-source-contracts.md). They return
canonical rows. `build_synthesized_parquet` writes those rows as a schema-v1 Parquet/provenance
bundle from a previously verified `InputSet`; it does not fetch inputs or publish artifacts remotely.

## Local native Parquet build provenance

A local per-program build is available only for `ap`, `ce`, `cu`, `ln`, and `oe`, from an explicit
verified HTTP `InputSet`. The input's downloaded record and SHA-256 recheck must agree; actual bytes
and size are checked against those records, and the exact privately staged, hash-verified snapshot is
parsed. The downloaded path is checked after parsing and again after output staging immediately before
publication; changes detected at those checks fail closed. This last check does not prevent the source
from changing afterward. This does not fetch data or publish artifacts.

Each completed local bundle contains `catalog.parquet` and `provenance.json` in a directory named by
the SHA-256 of the sidecar bytes. The Parquet file uses Zstandard compression and exactly the canonical
column order and types above. The JSON sidecar has `schema_version`, `program`, `row_count`,
`source_built_at`, `inputs`, and `artifact` fields. `source_built_at` is the injected build clock in
UTC with microseconds and a `Z` suffix; it is not read from source file metadata. Each input entry
records its source `url`, byte count, and SHA-256. The artifact entry records its relative `path`, byte
count, SHA-256, and compression. The build stages outputs privately and exposes them with an atomic
no-replace local directory operation; a concurrently created destination is verified and never
replaced or removed. Systems without that operation fail safely rather than using a racy fallback. This
local build layer has no download command, R2 integration, or publication behavior.

## Evidence

The 30 native header contracts, exact widths, UTF-8 decodability, no blank `.series` rows,
and examples of padded IDs are recorded in
[`evidence/2026-10-07-local-source-probe.json`](evidence/2026-10-07-local-source-probe.json)
and summarized in [`evidence/2026-10-07-gate0.md`](evidence/2026-10-07-gate0.md).
The program descriptions and examples of source period codes come from the local research
inventory [`../research/2026-08-11-existing-bls-series-catalogs.md`](../research/2026-08-11-existing-bls-series-catalogs.md).
