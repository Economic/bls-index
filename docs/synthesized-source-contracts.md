# Synthesized source contracts (bounded local parsing)

This document describes the implemented PR-only local parser. It does not initiate downloads,
write Parquet or provenance bundles, create commits, publish artifacts, or contact GitHub. The
`synthesized_builders` module accepts either explicit local paths (useful for tests) or an
already fetched `HttpSource` `InputSet`; the latter is integrity-checked and never triggers a
request.

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
implement `sm` or `jt`, or perform any publication or remote operation. Broader source-domain
verification beyond the checked-in fixture evidence remains deferred.
