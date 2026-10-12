# Catalog schema v1

Schema version 1 is the canonical row format for series records. This increment implements
local native-title parsing for `ap`, `ce`, `cu`, `ln`, and `oe`; it does not build a combined
catalog or publish anything.

## Columns

| Column | Type | Null? | Meaning and normalization |
|---|---|---:|---|
| `program` | string | no | The explicit BLS flat-file directory/program code passed to the builder. It is not inferred from the series ID. |
| `series_id` | string | no | Native BLS series identifier with source padding removed from both ends. IDs remain strings. Must contain only ASCII letters/digits, be nonempty, and be unique within a program. |
| `series_title` | string | no | The native source title, preserved byte-decoded Unicode text exactly (including leading/trailing spaces). A title containing only whitespace is invalid. Titles need not be unique. |
| `title_source` | string | no | `native` for these five builders. `synthesized` is reserved for later builders. |
| `seasonal` | string | no | `SA`, `NSA`, or `unknown`. Observed source code `S` maps to `SA`; `U` maps to `NSA`. A source with no seasonal field (such as `ap`) maps to `unknown`. |
| `begin_year` | int32 | yes | Four-digit positive year from the source, or null when the source field is blank. Descriptive metadata only, not a claim of current activity. |
| `end_year` | int32 | yes | Four-digit positive year from the source, or null when the source field is blank. Descriptive metadata only, not a claim of current activity. |
| `end_period` | string | yes | Trimmed source end-period code, or null when blank. Kept as the source code; no date is inferred. |

The canonical column order is exactly the table order. The schema version is separate from
any data-dictionary specification version.

## Native source contracts implemented here

The builders require the exact ordered headers observed by the 2026-10-07 local source probe:

- `ap`: `series_id, area_code, item_code, series_title, footnote_codes, begin_year, begin_period, end_year, end_period`
- `ce`: `series_id, supersector_code, industry_code, data_type_code, seasonal, series_title, footnote_codes, begin_year, begin_period, end_year, end_period`
- `cu`: `series_id, area_code, item_code, seasonal, periodicity_code, base_code, base_period, series_title, footnote_codes, begin_year, begin_period, end_year, end_period`
- `ln`: `series_id, lfst_code, periodicity_code, series_title, absn_code, activity_code, ages_code, cert_code, class_code, duration_code, education_code, entr_code, expr_code, hheader_code, hour_code, indy_code, jdes_code, look_code, mari_code, mjhs_code, occupation_code, orig_code, pcts_code, race_code, rjnw_code, rnlf_code, rwns_code, seek_code, sexs_code, tdat_code, vets_code, wkst_code, born_code, chld_code, disa_code, seasonal, tlwk_code, footnote_codes, begin_year, begin_period, end_year, end_period`
- `oe`: `series_id, seasonal, areatype_code, industry_code, occupation_code, datatype_code, state_code, area_code, sector_code, series_title, footnote_codes, begin_year, begin_period, end_year, end_period`

Padding around header names is accepted because observed BLS headers contain right-padding
before tabs. Data rows must have exactly the header's tab-separated field count. UTF-8 is
strict (no lossy replacement), blank lines and empty data rows are rejected, and control
characters in fields are rejected. The parser retains source row order.

IDs are checked for nonempty ASCII alphanumeric content and uniqueness within the explicit
program. There is intentionally no requirement that an ID begin with its program code:
source program/survey families do not universally match the directory code. The local
research documents `ce` as Current Employment Statistics, `cu` as Consumer Price Index,
`ln` as Labor Force Statistics from the CPS, `oe` as Occupational Employment and Wage
Statistics, and `ap` as Average Price Data; these are descriptive mappings, not ID prefixes.
The parser never assigns a survey name from a guessed prefix.

## Validation behavior and deferred verification

Blank begin/end years and end periods become null. Present years must be four decimal digits,
positive, and a non-null begin year cannot exceed a non-null end year. Present periods must
be a two-digit source token in a recognized monthly (`M`), quarterly (`Q`), or annual (`A`)
family with a positive ordinal; the implementation currently accepts `M01`–`M13`, `Q01`–
`Q05`, and `A01`. A period without an end year is rejected. These are syntax/range checks,
not a claim that every program uses every allowed code.

Seasonal codes in a column must be present and be `S` or `U`. The local probe fixture for
`pr.seasonal` records `S = Seasonal Adjusted` and `U = Not Seasonally Adjusted`; schema v1
uses the shorter canonical values `SA` and `NSA`. The probe confirms `ap` has no seasonal
column, so its canonical value is `unknown`.

**Deferred verification before production catalog assembly:** review the source-specific
metadata value domains (including all valid periods, exceptional years, and seasonal values)
against the five current `.series` files and authoritative BLS code tables; confirm whether
any supported program has legitimate values outside the bounded checks above. This increment
has no current-source download, row-count threshold, whole-scope cross-program uniqueness
check, combined Parquet/provenance build, or publication integration. Do not infer liveness
from year or period fields. `survey_name` and `begin_period` are intentionally deferred from
schema v1 until their normalization and verification are explicitly approved.

## Evidence

The five header contracts, exact widths, UTF-8 decodability, no blank `.series` rows, and
examples of padded IDs are recorded in
[`evidence/2026-10-07-local-source-probe.json`](evidence/2026-10-07-local-source-probe.json)
and summarized in [`evidence/2026-10-07-gate0.md`](evidence/2026-10-07-gate0.md).
The program descriptions and examples of source period codes come from the local research
inventory [`../research/2026-08-11-existing-bls-series-catalogs.md`](../research/2026-08-11-existing-bls-series-catalogs.md).
