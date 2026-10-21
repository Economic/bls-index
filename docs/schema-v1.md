# Catalog schema v1

One row per BLS series. The file is a Parquet file, compressed with zstd at level 19,
with exactly these columns, in this order. Machine-checkable constraints are in the repository-root
[`data-dict.yaml`](../data-dict.yaml). Schema version 1 is separate from the data-dict
specification `$version`.

## Columns

| Column | Type | Null? | Meaning and normalization |
|---|---|---:|---|
| `program` | string | no | BLS program (flat-file directory) code from the fixed scope in `src/bls_index/scope.py`. Never inferred from the series ID. |
| `survey_name` | string | no | The program's BLS survey name, the same for every row of a program. Sources are listed in [`survey-names.md`](survey-names.md). |
| `survey_aliases` | string | yes | Other names people search for (initialisms, former and informal names), separated by `; `. The same for every row of a program, or null when a program has none. Listed with reasons in [`survey-names.md`](survey-names.md). |
| `series_id` | string | no | BLS series identifier with source padding trimmed from both ends. Unique across the catalog. Compared exactly as spelled; no case folding. |
| `series_title` | string | no | For native-title programs, the source title exactly as published, including surrounding spaces. For `sm`, `jt`, and `pr`, a title synthesized from trimmed lookup labels (see [`synthesized-source-contracts.md`](synthesized-source-contracts.md)). Never blank. Titles need not be unique. |
| `title_source` | string | no | `native` or `synthesized`. |
| `seasonal` | string | no | `SA` when the source code is `S`, `NSA` when it is `U`, otherwise `unknown`. Programs without a seasonal column (such as `ap`) are `unknown`. |
| `begin_year` | int32 | yes | Four-digit source year, or null when the source field is blank. |
| `end_year` | int32 | yes | Four-digit source year, or null when the source field is blank. |
| `end_period` | string | yes | Trimmed source end-period code (such as `M08`, `Q02`, `S01`, `A01`), or null when blank. No date is inferred. |

## Rules

- A known `begin_year` is not later than a known `end_year`.
- Year and period fields are descriptive source metadata. They are not a claim that a
  series is live or frozen.
- `begin_period` is deferred from schema v1.
- Any incompatible change to columns, types, or meanings requires a new schema version
  published beside v1, under a new path prefix.
