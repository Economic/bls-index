# Synthesized source contracts (bounded local parsing)

This document describes bounded local parsers for SM, JT, and PR. They do not initiate downloads,
write Parquet or provenance bundles, create commits, publish artifacts, or contact GitHub. Each
program accepts exact explicit local paths or an already fetched `HttpSource` `InputSet`; the latter
is integrity-checked and never triggers a request. The parsers construct canonical rows only; no
per-program artifact integration is included.

The SM/JT full-input headers, row counts, source response hashes, and report excerpts were supplied
by a fresh double-read scan recorded in `tests/fixtures/real_synthesized/sm-jt-source-fixtures.json`
and `tests/fixtures/real_synthesized/sm-jt-series-descriptions.json`. Checked-in SM/JT parser
fixtures are compact subsets selected from that local source read, with their own hashes and
selection notes. They do not demonstrate that this parser has processed the complete double-read
inputs. A parent-run live parse remains separate verification work.

## SM inputs and observed evidence

The supplied source scan observed 22,927 `sm.series` rows and 20-character trimmed IDs. Its exact
ordered headers were:

- `sm.series`: `series_id, state_code, area_code, supersector_code, industry_code, data_type_code, seasonal, benchmark_year, footnote_codes, begin_year, begin_period, end_year, end_period`
- `sm.state`: `state_code, state_name`; `sm.area`: `area_code, area_name`
- `sm.supersector`: `supersector_code, supersector_name`; `sm.industry`: `industry_code, industry_name`
- `sm.data_type`: `data_type_code, data_type_text`; `sm.seasonal`: `seasonal_code, seasonal_text`

The parser trims lookup keys and labels, checks unique keys and nonblank labels across all rows,
and joins each series row to all title dimensions. It checks the trimmed ID against the observed
SM prefix, seasonal code, and the source state, area, industry, and data-type codes. It also checks
that `supersector_code` agrees with the first two characters of `industry_code`; this is an observed
cross-check, not a claim of a universal SM identifier rule. This saved scan observed all IDs
following that concatenation and the supersector prefix match across its rows. Seasonal lookup
text is required to match `S` → `Seasonally Adjusted` and `U` → `Not Seasonally Adjusted`, which
normalize to canonical `SA` and `NSA`. Dates use the bounded year/period validation described
below. `benchmark_year` and `footnote_codes` are not canonical output or title fields.

## JT inputs and observed evidence

The supplied source scan observed 2,060 `jt.series` rows and 21-character trimmed IDs. Its exact
ordered headers were:

- `jt.series`: `series_id, seasonal, industry_code, state_code, area_code, sizeclass_code, dataelement_code, ratelevel_code, footnote_codes, begin_year, begin_period, end_year, end_period`
- `jt.industry`, `jt.state`, `jt.area`, `jt.sizeclass`, `jt.dataelement`, and `jt.ratelevel` each have their `<dimension>_code, <dimension>_text, display_level, selectable, sort_sequence` headers.
- `jt.seasonal`: `seasonal_code, seasonal_text`

The parser validates the full ordered headers and row widths, every trimmed lookup key and label
(including unused lookup rows), required joins, unique trimmed IDs, and the observed JT ID layout and
component concatenation. This layout is observed in the supplied file, not asserted as a universal
official JT rule. JT seasonal text uses the same explicitly checked `S`/`U` mapping as SM and
normalizes separately to canonical `SA`/`NSA`. Date validation is bounded as described below;
`footnote_codes` is not emitted.

## PR inputs and evidence limits

The supported names and ordered headers are those recorded by the 2026-10-07 local source
probe (`docs/evidence/2026-10-07-local-source-probe.json`) and the checked-in local fixtures
under `tests/fixtures/two_program/pr/`:

- `pr.series`: `series_id, sector_code, class_code, measure_code, duration_code, seasonal, base_year, footnote_codes, begin_year, begin_period, end_year, end_period`
- `pr.sector`: `sector_code, sector_name, display_level, selectable, sort_sequence`
- `pr.class`: `class_code, class_text, display_level, selectable, sort_sequence`
- `pr.measure`: `measure_code, measure_text, display_level, selectable, sort_sequence`
- `pr.duration`: `duration_code, duration_text, display_level, selectable, sort_sequence`
- `pr.seasonal`: `Seasonal_code, Seasonal_text`

Files are strict UTF-8 tab-separated text with exact ordered headers and row widths. Lookup
keys and labels are trimmed at both ends. Blank keys or labels are rejected, as are duplicate
keys that become equal after trimming. Required code-to-label joins must exist. The seasonal
lookup is consumed and checked; only the observed `S` and `U` keys and their checked fixture
labels (`Seasonal Adjusted`, `Not Seasonally Adjusted`) are accepted. They normalize to `SA`
and `NSA`.

For each series row, the parser trims `series_id`, `sector_code`, `class_code`, `measure_code`,
`duration_code`, `seasonal`, `begin_year`, `end_year`, `begin_period`, `end_period`, and
`base_year`. The trimmed component codes and seasonal code are lookup keys and are used to
check that the series ID matches its components; blank or missing keys are rejected. The
trimmed ID must match the observed layout and be unique. Trimmed years and periods are subject
to bounded format, range, and consistency validation. For an `Index (YYYY=100)` duration label,
the trimmed `base_year` must match `YYYY`; other duration labels do not trigger that check.

The parser retains one canonical row per input series row in source order and returns exactly
the schema in `docs/schema-v1.md`. It emits the trimmed ID, lookup-label-based title, normalized
seasonal value, integer begin/end years, and trimmed end period (or null when blank). The
trimmed begin period, component codes, and `base_year` are used for validation but are not
canonical output fields. The checked-in PR sample IDs follow `PR`, seasonal `S`/`U`, then the
sector, class, measure, and duration codes, producing the fixture-observed layout `PR[SU]`
plus eight digits. The parser enforces that layout and case-insensitive component equality but
treats it as a local fixture contract, not a universal official ID specification.

## Independent report evidence for PR title fields

The checked-in excerpt fixture `tests/fixtures/real_synthesized/pr-series-descriptions.json` records
independently fetched official BLS series reports for [PRS30006011](https://data.bls.gov/timeseries/PRS30006011),
[PRS30006012](https://data.bls.gov/timeseries/PRS30006012), and
[PRS30006013](https://data.bls.gov/timeseries/PRS30006013). The offline builder test compares each
report's Measure, Sector, and Duration fields with the corresponding generated title components.
These reports do not expose Class; therefore `All workers` is supported by the checked-in PR class
lookup fixture, but is not independently verified by these official reports. The excerpts are not
official full synthesized titles and do not establish broader PR source contracts.

## Approved title

The title is exactly the following template, with lookup labels trimmed at their edges and
separated by semicolon-space:

```text
Measure: {measure}; Sector: {sector}; Class: {class}; Duration: {duration}
```

For the first fixture series, the exact title is:

```text
Measure: Employment; Sector: Manufacturing; Class: All workers; Duration: % Change same quarter 1 year ago
```

No other fields, including seasonal wording, footnotes, or `base_year`, are added to the title.
The local PR sample shows `duration_code` 1–3; rows with the duration label `Index (2017=100)`
have `base_year` 2017, while the non-index duration rows have `base_year` `-`. As a bounded
fixture rule, when a duration label explicitly matches `Index (YYYY=100)`, the parser requires
the row's `base_year` to equal that year, rejecting missing or contradictory values before it
emits the title. A base year on another duration label is not interpreted by this rule. This
check does not add `base_year` to the approved title or canonical output, and does not claim a
universal PR source contract.

## Integrity and deferred work

The path-based parser snapshots and hashes every supplied local input and checks the source
paths again after parsing. The `InputSet` API verifies exact PR input names, URL paths, matching
initial/recheck hashes and byte counts, and the actual file bytes before parsing the private
snapshots; it checks source files again after parsing. This reuses the native snapshot/hash
helpers and makes no weaker concurrent-mutation assumption.

This phase does not integrate a synthesized Parquet/provenance bundle, alter the live fetcher,
or perform any publication or remote operation. Broader source-domain verification beyond the
checked-in fixture evidence remains deferred.
