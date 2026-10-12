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
- Test rows in `tests/fixtures/native/constructed_rows.json` are compact constructed
  data, not copied from BLS. Existing `ap`, `ce`, `cu`, `ln`, and `oe` fixtures remain
  the original focused parser fixtures. No bulk raw source files are included.

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
code is inferred from ID prefixes or titles.

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
