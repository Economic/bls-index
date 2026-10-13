# Native-title source contracts (Phase 1)

The native builders support the fixed 30-program tier whose source `.series` files
contain `series_title`, as listed in the local research inventory. The builder requires
an explicit program code and matches a program-specific, ordered header tuple in
`src/bls_index/native_builders.py`; it does not derive headers from input contents,
series-ID prefixes, reports, or a shared schema guess.

## Evidence and review boundaries

- Current ordered header tuples, field-count histograms, row counts, and file hashes
  were recorded by the local source probe dated 2026-10-07 in
  [`evidence/2026-10-07-local-source-probe.json`](evidence/2026-10-07-local-source-probe.json).
  `test_supported_programs_match_observed_probe_headers_and_widths` checks every
  implemented tuple against those observations. The report is test/documentation
  evidence only; production code does not load it.
- Program-specific seasonality documentation is available from the official BLS
  time-series directory, for example [`bd.txt`](https://download.bls.gov/pub/time.series/bd/bd.txt)
  and its [`bd.seasonal` mapping](https://download.bls.gov/pub/time.series/bd/bd.seasonal).
  The official [BLS seasonal-adjustment help](https://www.bls.gov/help/hlpseas.htm)
  describes the `U` convention as unadjusted. For `cx`, both
  [`cx.txt`](https://download.bls.gov/pub/time.series/cx/cx.txt) and
  [`cx.seasonal`](https://download.bls.gov/pub/time.series/cx/cx.seasonal) returned
  HTTP 404, so no `S` meaning is established for that program.
- A fresh verification of the official
  [`cx.series`](https://download.bls.gov/pub/time.series/cx/cx.series) download on
  2026-10-12 fetched the file twice with matching SHA-256
  `9755a92a6605d05bae92ca34080b4214500603dd487c37090e0e1ed95b8432f2`;
  its 183,935 rows all had seasonal code `U`. Sample series ID: `CXU001000LB0101M`.
  Combined with the general BLS `U` convention, this supports mapping observed `U` to
  `NSA`. It does not establish that `S` is valid for `cx`; all other nonblank or blank
  values in this known field are rejected.
- Program ownership for series IDs is checked against explicit leading survey codes in
  `SERIES_ID_PREFIXES`; IDs are never used to infer which adapter to run. The mapping is
  based on each official program's `.txt` ID example, with the exception of `cx`: its
  [`cx.txt`](https://download.bls.gov/pub/time.series/cx/cx.txt) document returned HTTP
  404, so `CX` is confirmed from the verified `cx.series` file. IDs use ASCII letters,
  digits, and program-specific separators; IDs must start with the requested program's
  code, case-insensitively. The current native adapters accept `_` for `ip` and `-` for
  `nd`, `oe`, and `pc`; other programs accept only letters and digits. Thus a row carrying
  a `CES...` ID in an `ap` file is rejected rather than reassigned.
  The explicit leading-code contract for the 30 native-title programs is:

  | Program | ID begins with | Program | ID begins with | Program | ID begins with |
  |---|---|---|---|---|---|
  | `ap` | `AP` | `bd` | `BD` | `ce` | `CE` |
  | `ci` | `CI` | `cm` | `CM` | `cu` | `CU` |
  | `cw` | `CW` | `cx` | `CX` | `ei` | `EI` |
  | `ep` | `EP` | `fm` | `FM` | `ip` | `IP` |
  | `is` | `IS` | `kv` | `KV` | `la` | `LA` |
  | `le` | `LE` | `ln` | `LN` | `lu` | `LU` |
  | `mp` | `MP` | `nb` | `NB` | `nd` | `ND` |
  | `oe` | `OE` | `or` | `OR` | `pc` | `PC` |
  | `su` | `SU` | `tu` | `TU` | `wd` | `WD` |
  | `wm` | `WM` | `wp` | `WP` | `ws` | `WS` |

  Observed `_` and `-` separators are permitted in the remainder of IDs, including the
  verified `ip` and `nd` samples; full-file validation also observed embedded separators
  in an `oe` industry component. Whole-layout source comparisons are listed in
  `SERIES_ID_COMPONENTS`; independently verified source-field slices for incomplete or
  non-contiguous mappings are listed in `SERIES_ID_FIELD_SLICES`. A partial slice check
  constrains only the named source field at the documented ID position: every unlisted
  ID position and unrelated source field remain opaque. IDs are also checked against their
  program prefix, program-specific length and character constraints, and any applicable
  seasonal character rule. These checks validate reported source fields;
  they do not decode every characteristic in a series ID or establish categorical code
  validity from mapping files.

  Local offline inspection of official BLS `.txt` definitions saved in the session output
  (no network fetch or live revalidation in this change) supports the following. URLs are
  authoritative BLS documents; each SHA-256 is the identifier recorded beside that
  document in the saved output. For EI, LU, TU, NB, and WM the official text provides a
  complete ID decomposition; the parser cross-checks every segment that has an exact
  source-column counterpart. This does not make a human-readable name or composite code
  into a source ID field: EI's `series_name`, LU's `stype_code`/`seq_code`, and TU's
  composite `character_code` are not compared to guessed source values.

  | Program | Official definition | SHA-256 recorded in saved output | Supported ID/source comparisons |
  |---|---|---|---|
  | `ei` | [`ei.txt`](https://download.bls.gov/pub/time.series/ei/ei.txt) | `627a8941cf11ad87072dff8deaae44a76be908bcc1dc148ba88e95cdfc16f2ac` | `index_code` (ID positions 3–4); the official decomposition also names the remaining `series_name`, but only the index-code agreement is asserted here. |
  | `ci` | [`ci.txt`](https://download.bls.gov/pub/time.series/ci/ci.txt) | `bb0bdc159fc18a91b675b07cb78bc43170f135cbf3e62184edb52dcce19b626d` | owner, estimate, and periodicity at their documented ID positions. Industry, occupation, and subcell are opaque to ID validation: full-source comparisons do not establish universal mappings, including the observed `CIU1010000000710A` row where source subcell `27` differs from ID slice `71`. Other ID positions are also opaque because the documented widths and example do not form a complete one-to-one layout. |
  | `cm` | [`cm.txt`](https://download.bls.gov/pub/time.series/cm/cm.txt) | `dc606274517a9b2f21b8e4bd99bf47d1c0500184c9ce39e91faf92fe6da34bf1` | owner at ID position 3 and datatype at position 16 only; other source dimensions are not assumed from the inconsistent example/field widths. |
  | `fm` | [`fm.txt`](https://download.bls.gov/pub/time.series/fm/fm.txt) | `921aaa15df9b3e8bc1a60788091aa7b64f90724aab5219dde9c27b6840471143` | Program and seasonal prefix only; no suffix layout asserted. |
  | `kv` | [`kv.txt`](https://download.bls.gov/pub/time.series/kv/kv.txt) | `2c5eee6d0f97890a2ea0aab98ef0ec0268a203d552e340a7583c4297d5952e41` | Program and seasonal prefix only. The definition explicitly says the remaining ID digits cannot be decoded into attributes. |
  | `le` | [`le.txt`](https://download.bls.gov/pub/time.series/le/le.txt) | `1281c6d707cc85c357909a0447dbda7572e6852ffa7b1ada4b4e7efbd6fb5ee6` | Program and seasonal prefix only; no suffix layout asserted. |
  | `ln` | [`ln.txt`](https://download.bls.gov/pub/time.series/ln/ln.txt) | `a9a089a9294b49a851d38aca16342028cd4bd95e8e0149bb00a470298065db0c` | Program and seasonal prefix only. The definition says attributes cannot be decoded from the remaining ID positions. |
  | `lu` | [`lu.txt`](https://download.bls.gov/pub/time.series/lu/lu.txt) | `e4a6e6b0dcb873652466dcec8d235f525be44a4ca9bf4ba69fe7ff3b8b3a2b64` | `lfst_code` and `fips_code`; intervening positions are not asserted because the current source columns do not preserve all fields in the official example. |
  | `tu` | [`tu.txt`](https://download.bls.gov/pub/time.series/tu/tu.txt) | `be7ba131fb9c45b52ace64762d25c7296601c004aa71d359fe31ba19cba9eb9a` | `stattype_code` and `datays_code`; remaining composite character positions are opaque. |
  | `nb` | [`nb.txt`](https://download.bls.gov/pub/time.series/nb/nb.txt) | `b7ad02eb5a384d90a99ac904dd4098055693e59a01fed544d8630c290e0ec743` | Ownership, estimate, occupation, subcell, datatype, and provision code; the industry source field remains opaque to ID validation because the recorded `611100` value does not establish a universal mapping to the apparent `6110` ID slice. This retains the source `subcell_code` omitted by the earlier proposed layout. |
  | `or` | [`or.txt`](https://download.bls.gov/pub/time.series/or/or.txt) | `2b39501038068cae61b97c905204af2c8f8e6a7088c33c70fa9f41ec3be801f7` | Requirement, ownership, industry, occupation, and job-characteristic fields only. The official example's final estimate positions conflict with retained source rows, so estimate and datatype fields are not asserted. |
  | `wm` | [`wm.txt`](https://download.bls.gov/pub/time.series/wm/wm.txt) | `b7ba3485a37356b7945b9b493296a16dedf75ba6c86cbbd6566943741287bfe2` | Area, ownership, estimate, industry, occupation, subcell, and level; datatype is not part of the documented ID decomposition. |

  `ep`, `is`, `mp`, and `ws` whole layouts remain sample-verified only, including the
  `ep` removal of hyphens from `occ_code` and `ind_code`; no official `.txt` confirmation
  for those mappings is recorded. For `wp`, the local validation evidence records one
  source row with `group_code` `PFF`, `item_code` `PLUS02`, and ID `WPS01PLUS02`; the parser
  maps `PFF` to ID component `01`. The full group relationship scan also supports the
  explicit `ILF` and `IND` aliases to ID component `03`. The subsequent
  [six-program full-source revalidation](evidence/2026-10-13-native-six-revalidation.json)
  passes all six formerly rejected files with matching download hashes and records the
  exact parser hash; it does not replace the earlier all-30 failure evidence.
  Group comparisons are case-insensitive;
  other values are compared directly, so these aliases do not waive group checks. The prefixes
  remain checks after the caller selects an explicit adapter; they never select the program. All mappings,
  including slices, are evidence-bounded and do not claim coverage of every valid ID.
- Small real-source samples for each of the 30 native programs are in
  [`../tests/fixtures/real_native/`](../tests/fixtures/real_native/). Each metadata JSON
  records the official URL, retrieval date, two matching SHA-256 reads, source row count,
  selected first/midpoint/last rows, raw fields, expected canonical values or parser error,
  and full-file parse status. The fixture tests compare those expectations and preserve
  the native series title. No bulk raw source files or request User-Agent are included.
- `tests/fixtures/native/full_revalidation_id_rows.json` preserves the ten parsed row
  dictionaries rejected by a saved full-file validation run. The captured output did not
  include raw TSV lines, so these are explicitly marked constructed-from-record and used
  only as offline parser regressions, not as verbatim BLS source samples. Component equality
  is checked only for source layouts represented by `SERIES_ID_COMPONENTS` or the explicitly
  supported partial ID slices in `SERIES_ID_FIELD_SLICES`.
- The official [`cu.txt`](https://download.bls.gov/pub/time.series/cu/cu.txt) and
  [`cw.txt`](https://download.bls.gov/pub/time.series/cw/cw.txt) documentation specifies
  `M01-M13` and `S01-S03` for begin/end periods, defines `S` as semi-annual, and says `S03`
  indicates annual averages. This supports accepting `S01`, `S02`, and `S03` only for `cu`
  and `cw`; no other program's period family is widened. Current BLS `cu.series` and
  `cw.series` files contain examples of all three codes and both files now parse fully.
  The compact fixtures include exact source rows containing `S01`, `S02`, and `S03` values
  plus their expected canonical output. The small current `su.series` file has no semi-annual periods,
  so no `S` support is added there.
- `full_file_parse` in `cu.json`/`cw.json` and the corresponding manifest
  `full_file_parse_failures` preserve the original 2026-10-12 results from before this
  period-contract correction. They are explicitly labeled historical. Separate
  `current_full_file_revalidation` records document subsequent twice-hash-verified reads
  and successful full parses (8,104 `cu` rows; 7,868 `cw` rows); the manifest cross-checks
  those current results against each program record.
- Test rows in `tests/fixtures/native/constructed_rows.json` are compact constructed
  data, not copied from BLS. Existing `ap`, `ce`, `cu`, `ln`, and `oe` fixtures remain
  the original focused parser fixtures.

## Programs and seasonality

Every program below has an explicit exact tuple in `SOURCE_HEADERS`. This summary does
not expand the tuples into a second, manually maintained copy; the probe comparison test
is the source-contract check for the complete ordered columns.

| Program | Seasonal field policy |
|---|---|
| `oe`, `is`, `wm`, `ep`, `nb`, `tu`, `or`, `ln`, `bd`, `la`, `ce`, `ip`, `le`, `wd`, `cu`, `cm`, `cw`, `nd`, `wp`, `pc`, `fm`, `ci`, `ei`, `lu`, `su`, `ws` | Official documentation identifies `S` as seasonally adjusted and `U` as unadjusted. Both are accepted and mapped to `SA` / `NSA`. |
| `kv` | Official documentation says the series are unadjusted (`U`) and seasonal adjustment does not apply; only `U` is accepted and maps to `NSA`. |
| `cx` | A verified `cx.series` file contained only `U` values. With the general BLS convention that `U` means unadjusted, `U` maps to `NSA`. `S` has not been verified for this program and is rejected. |
| `ap`, `mp` | No seasonal column in the observed exact headers; canonical seasonality is `unknown`. |

For programs whose documentation describes S/U codes generally but gives only an example
of one code for a specific source, accepted values remain the documented two-code domain
where that domain is explicitly stated. `cx` is deliberately narrower: only its observed
`U` value is accepted, with no unverified `S` support. Blank values in any present seasonal
field are rejected unless an official source documents blank as a valid value; none of these
contracts documents it. Programs without a seasonal field normalize to `unknown`. No source
code is inferred from ID prefixes or titles. Where a seasonal field is present, its `S` or
`U` value must also match the third character of the series ID; this cross-check is in
addition to validating the program-specific source seasonality policy.

## Layout and nullable metadata

The current probe observes a date-bearing `kv.series` header and correctly width-matched
rows. The local historical inventory says some older `kv` series data had no begin/end
year fields, but it does not preserve that exact old header tuple. The adapter therefore
accepts only the current observed tuple; it does not guess the historical variant or
accept arbitrary missing/reordered columns. Blank current `kv` dates are null in the
canonical output, as with other optional source dates. Add a historical `kv` variant only
after obtaining its exact header and a validating local fixture.

Other reported research anomalies (`cc` concatenated first header/data line, trailing
undeclared fields in `eb`, `ec`, `ee`, `gp`, `hs`, `pd`, `sa`, `sh`, and `si`, and the
shifted `hs` years) concern other fixed-schema/synthesized programs, not these 30 native-
title programs. They are not silently generalized into native adapters.

## Stable behavior

The parser preserves input order and native title text, trims padded IDs and selected
metadata fields, rejects malformed UTF-8, controls, blank rows, unexpected headers and
row widths, and converts blank dates/periods to null where represented in schema v1.
It validates dates as optional metadata only; it does not infer that a series is live.
The existing private snapshot and source-checksum checks remain in place.
