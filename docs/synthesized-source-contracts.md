# Synthesized titles: sm, jt, pr

These three programs have no `series_title` column, so `builders.synthesize` builds titles
from lookup files. The rules are data in `builders.SYNTHESES`; this page explains them.
Output rows follow [`schema-v1.md`](schema-v1.md) with `title_source = synthesized`.

## Templates

Each placeholder is the matching lookup label with surrounding spaces trimmed. Components
appear in this order, separated by `; `:

```text
pr: Measure: {measure}; Sector: {sector}; Class: {class}; Duration: {duration}
sm: Data type: {data_type}; State: {state}; Area: {area}; Supersector: {supersector}; Industry: {industry}
jt: Data element: {dataelement}; Rate/level: {ratelevel}; Industry: {industry}; State: {state}; Area: {area}; Size class: {sizeclass}
```

The `pr:`, `sm:` and `jt:` prefixes only identify the templates; they are not part of
titles. Seasonal adjustment is stored in the `seasonal` column, not the title, but
seasonal wording already inside a lookup label is kept.

## Inputs and joins

For a program `p` and each title dimension `d`, the builder reads `p.d` and joins it to
`p.series` on the column `d_code`. The label column is:

| Program | Dimension → label column |
|---|---|
| `pr` | sector → `sector_name`, class → `class_text`, measure → `measure_text`, duration → `duration_text` |
| `sm` | state → `state_name`, area → `area_name`, supersector → `supersector_name`, industry → `industry_name`, data_type → `data_type_text` |
| `jt` | industry, state, area, sizeclass, dataelement, ratelevel → `<dimension>_text` |

Columns are found by name, so extra or reordered columns are accepted. The seasonal
lookup files are not downloaded: seasonal codes map directly, `S` to `SA` and `U` to `NSA`.

## Checks

A program fails if any of these hold:

- a lookup key is blank or appears twice, or a label is blank (both after trimming)
- a series row's code is not in its lookup file
- a series ID does not equal the program code, the seasonal code, and the ID codes below,
  concatenated (compared case-insensitively):
  - `pr`: sector, class, measure, duration
  - `sm`: state, area, industry, data type
  - `jt`: industry, state, area, size class, data element, rate/level
- for `sm`, `supersector_code` differs from the first two characters of `industry_code`
- the output row count differs from the `.series` row count

The ID check matters because the codes choose the title. A code that exists in its
lookup but disagrees with the ID would otherwise give a valid-looking but wrong title.

For `pr`, a row whose duration label is `Index (YYYY=100)` but whose `base_year` is not
`YYYY` is logged as a warning and recorded in the build report; it does not fail the
program. `base_year` is not published, and the title comes from the label.

The shared rules in `schema.py` also apply: nonblank, unique IDs starting with the program
code, nonblank titles, and four-digit years.

## Evidence

Official BLS series reports checked on 2026-10-12 and 2026-10-13 are saved in
`tests/fixtures/real_synthesized/*-series-descriptions.json`. The tests compare their
fields with the generated titles. The PR reports do not show Class, so the "All workers"
component is checked only against the lookup file. Full-source validation of all three
programs is recorded in
[`2026-10-13-sm-jt-validation.json`](https://github.com/Economic/bls-index/blob/pre-cleanup/docs/archive/evidence/2026-10-13-sm-jt-validation.json)
and [`2026-10-13-pr-validation.json`](https://github.com/Economic/bls-index/blob/pre-cleanup/docs/archive/evidence/2026-10-13-pr-validation.json),
at the git tag `pre-cleanup`.
On 2026-10-20, the current builders reproduced the earlier builders' output exactly on a
full download (`scripts/golden.py`).
