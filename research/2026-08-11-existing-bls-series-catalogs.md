# Does a public BLS series ID catalog already exist?

Reconnaissance notes, 2026-08-11.

## The question

The BLS Data Finder was the only tool that let you search human-readable terms and
recover BLS series IDs, titles, and metadata. It has been down for weeks.
`epidatatools::find_bls()` wraps it, so that function is broken too.

Proposed replacement: a public, frequently updated site holding all series IDs and
series titles from the downloadable flat files
(`https://download.bls.gov/pub/time.series/`), browsable as a web page and available
through a simple API.

Does something like this already exist?

## Short answer

A public series-ID lookup site does exist: [BLS Series Lookup](https://prestonmui.github.io/bls-series-lookup/)
searches descriptions and IDs for 11 programs. It does not cover OEWS, and its repository
shows no documented automatic data-refresh pipeline. DBnomics offers broader coverage
(roughly 40 percent of the programs), though its updates lag. Neither provides the
proposed broad, daily-refreshed index.

## Confirmed status of BLS tooling

- **Data Finder is officially down, not merely flaky.** `data.bls.gov/dataQuery/search`
  returns a 302 to a ["Data Finder maintenance"](https://www.bls.gov/bls/data-query-not-available.htm)
  page stating the tool is unavailable until further notice.
- **The official BLS API offers no discovery endpoint.** [API features](https://www.bls.gov/bls/api_features.htm)
  covers data retrieval by series ID only. There is no series search and no metadata
  lookup. You must already know the ID.
- **`pub/time.series/sdmx/` is not a catalog.** It contains five SDDS+ XML files
  (`sddsplus_bls_cpi.xml`, `_emp`, `_ppi`, `_uem`, `_woe`), not series metadata.
- **Surviving BLS tools all presuppose the ID**: [Series Report](https://data.bls.gov/series-report),
  the per-program one-screen databases, and the
  [series ID format guides](https://www.bls.gov/help/hlpforma.htm).

## Existing options

### DBnomics: the closest thing by far

<https://db.nomics.world/BLS> ingests the BLS flat files
([fetcher source](https://git.nomics.world/dbnomics-fetchers/bls-fetcher)) and keeps the
real BLS series IDs as its series codes. Free, keyless, full-text search:

```
https://api.db.nomics.world/v22/series/BLS/ce?q=average+hourly+earnings+manufacturing
```

returns `num_found: 720` and, for example:

```
CES3000000003 | AVERAGE HOURLY EARNINGS OF ALL EMPLOYEES – Manufacturing – Seasonally Adjusted
CES3000000008 | AVERAGE HOURLY EARNINGS OF PRODUCTION AND NONSUPERVISORY EMPLOYEES – Manufacturing – SA
CES3000000013 | AVERAGE HOURLY EARNINGS OF ALL EMPLOYEES, 1982-1984 DOLLARS – Manufacturing – SA
```

There is also a browsable web UI and R, Python, and Stata clients (`rdbnomics`).

Limits:

- **Coverage is 27 of about 66 flat-file datasets.**
  - Present: `ap cw cu pc wp fm lu jt tu ln bd ce sm la ws su ci le cm nb wm cx mp pr ip is ei`
  - Absent: `bg bp ca cb cc cd cf ch cs eb ec ee ep esbr fa fi fw gg gp hc hs ii in jl kv li ml mu mw nc nd nw oe or pd sa sh si wd`
  - Notable absences: `oe` (OEWS), `eb`/`ec`/`cb`/`cc` (benefits, ECEC), `or` (ORS).
- **Refresh lags and varies by dataset.** `ce` last indexed 2026-03-12, `sm` 2026-01-28.
- **Search runs over DBnomics-constructed series names**, not the native BLS
  `series_title` or the program code tables.

### Other partial options

| Option | What it gives | Why it falls short |
| --- | --- | --- |
| [BLS Series Lookup](https://prestonmui.github.io/bls-series-lookup/) ([source](https://github.com/PrestonMui/bls-series-lookup)) | Browser search by description or ID across 11 programs; program and seasonal-adjustment filters, multi-select, copy, and CSV export | No OEWS or other programs outside its 11; its build embeds CSV snapshots in the page, with no documented automatic refresh or downloadable catalog. Latest data-directory commit observed 2026-05-07 (checked 2026-09-25) |
| [FRED](https://fred.stlouisfed.org/) | Strong search API; for CPI, CES, and LAUS it often reuses the BLS ID verbatim | Curated subset. Deep detail (OEWS occupation by area, ORS, ECEC) largely absent |
| [blscrapeR](https://github.com/keberwein/blscrapeR) | Bundles roughly 75,000 series IDs with fuzzy search | Frozen snapshot of "popular" series; package effectively unmaintained |
| [BLSloadR](https://schmidtdetr.github.io/BLSloadR/) | Streamlines flat-file downloads | Machinery for fetching, not a hosted searchable index |
| [tidyusmacro `getBLSFiles`](https://www.mikekonczal.com/tidyusmacro/reference/getBLSFiles.html) | Same idea, different package | Same gap |
| [Singer tap-bls](https://github.com/frasermarlow/tap-bls) | ETL for a configured handful of series | Not a catalog |
| Kaggle [`bls/bls`](https://www.kaggle.com/datasets/bls/bls), BigQuery public BLS | Bulk data for a few programs | Data, not a series index; stale |

## Verified build constraints

Two findings that will shape any implementation.

1. **`download.bls.gov` requires a descriptive User-Agent.** A bare `curl` returns 403.
   With `-A "epi research (bzipperer@epi.org)"` it returns 200. BLS wants contact
   information in the header.

   ```
   curl -s -o /dev/null -w "%{http_code}" https://download.bls.gov/pub/time.series/ce/ce.series
   # 403
   curl -s -o /dev/null -w "%{http_code}" -A "epi research (bzipperer@epi.org)" \
     https://download.bls.gov/pub/time.series/ce/ce.series
   # 200
   ```

2. **`series_title` is not universal across programs.** `ce`, `la`, and `cu` include it.
   Other programs supply only dimension codes, so a searchable title has to be
   synthesized by joining each program's lookup files (`ce.industry`, `ce.datatype`, and
   so on). That per-program join logic is the real work, and it is precisely where
   DBnomics' name construction is weakest.

Additional notes:

- The flat-file root lists 67 directories (66 program directories plus `compressed`).
- Some directories are long stale upstream (`bg`, `cd`, `cf`, `ee` last modified
  2024-03-13), so a refresh job should respect per-directory modification times rather
  than re-pulling everything.
- Several programs are large (`oe`, `nw`, `is`), which matters for index size and for
  any client-side search design.
- Series churn is real: CES discontinued roughly 900 series with the January 2026 data
  release and the 2025 benchmark. An index should record when a series disappears
  instead of silently dropping it.

## Corpus inventory

Measured 2026-08-11 by reading the header line and counting rows of every `.series`
file.

- 67 directories under `pub/time.series/`, of which `compressed` and `sdmx` are not
  programs and `esbr` has no `.series` file. **65 programs are in scope.**
- **14.6 GB** of raw `.series` metadata.
- **Roughly 184 million series in total**, of which only about 22 million are
  realistically searchable. The distribution is extremely lopsided.

### Tier 1: native `series_title` (30 programs, 8,287,846 series, 1.54 GB)

Exact counts. These ship a prose title and need no synthesis.

| Program | Name | Series | Size |
|---|---|---|---|
| `oe` | Occupational Employment and Wage Statistics | 6,023,970 | 1203.0 MB |
| `is` | Occupational Injuries and Illnesses Industry Data | 891,324 | 119.9 MB |
| `wm` | Modeled Wage Estimates | 557,753 | 103.5 MB |
| `cx` | Consumer Expenditure Survey | 183,935 | 29.7 MB |
| `ep` | Employment Projections | 113,473 | 17.7 MB |
| `nb` | National Compensation Survey, Benefits | 100,124 | 23.6 MB |
| `tu` | American Time Use Survey | 87,387 | 22.9 MB |
| `or` | Occupational Requirements Survey | 73,711 | 14.4 MB |
| `ln` | Labor Force Statistics from the CPS | 68,630 | 14.6 MB |
| `bd` | Business Employment Dynamics | 34,464 | 5.4 MB |
| `la` | Local Area Unemployment Statistics | 33,985 | 3.9 MB |
| `ce` | Current Employment Statistics, National | 22,049 | 3.8 MB |
| `ip` | Industry Productivity | 21,134 | 3.8 MB |
| `le` | CPS Earnings | 11,053 | 2.4 MB |
| `wd` | Producer Price Index, Commodity (discontinued) | 8,536 | 1.5 MB |
| `cu` | Consumer Price Index, All Urban Consumers | 8,104 | 1.3 MB |
| `cm` | Employer Costs for Employee Compensation | 7,998 | 1.5 MB |
| `cw` | Consumer Price Index, Urban Wage Earners | 7,868 | 1.4 MB |
| `nd` | Producer Price Index | 6,509 | 1.3 MB |
| `wp` | Producer Price Index, Commodity | 5,310 | 0.9 MB |
| `mp` | Major Sector Total Factor Productivity | 4,683 | 0.7 MB |
| `pc` | Producer Price Index, Industry | 4,509 | 0.8 MB |
| `fm` | Marital and Family Labor Force Statistics | 3,144 | 0.6 MB |
| `ci` | Employment Cost Index | 2,470 | 0.5 MB |
| `ei` | International Price Index | 1,593 | 0.4 MB |
| `ap` | Average Price Data | 1,483 | 0.2 MB |
| `kv` | CPS Veterans Supplement | 1,371 | 0.2 MB |
| `lu` | CPS Union Affiliation | 1,241 | 0.2 MB |
| `su` | Chained CPI, All Urban Consumers | 29 | tiny |
| `ws` | Work Stoppage Data | 6 | tiny |

OEWS alone is 73 percent of tier 1.

### Tier 2: no title, fixed schema, cheap synthesis (25 programs, 13,724,238 series, 1.27 GB)

Exact counts. No `series_title`, but every dimension column has fixed semantics, so a
per-program template over the small lookup tables produces a title mechanically.

| Program | Name | Series | Size |
|---|---|---|---|
| `nw` | National Compensation Survey | 12,532,090 | 1195.2 MB |
| `ii` | Occupational Injuries and Illnesses Industry Data | 864,870 | 55.3 MB |
| `ml` | Mass Layoff Statistics (discontinued) | 62,423 | 3.3 MB |
| `nc` | National Compensation Survey | 59,990 | 3.8 MB |
| `sh` | Occupational Injuries and Illnesses Incidence Rates | 45,738 | 2.2 MB |
| `sa` | State and Area Employment, Hours and Earnings | 36,807 | 2.3 MB |
| `sm` | State and Area Employment, Hours and Earnings | 22,927 | 1.8 MB |
| `hs` | Occupational Injuries and Illnesses Incidence Rates | 18,762 | 1.1 MB |
| `pd` | Producer Price Index | 17,439 | 1.2 MB |
| `si` | Occupational Injuries and Illnesses Incidence Rates | 15,212 | 0.9 MB |
| `gp` | Geographic Profile | 13,654 | 0.8 MB |
| `mu` | Consumer Price Index | 7,600 | 0.5 MB |
| `mw` | Consumer Price Index, Urban Wage Earners | 7,590 | 0.5 MB |
| `cc` | Employer Costs for Employee Compensation | 5,075 | 0.3 MB |
| `ee` | Employment, Hours, and Earnings, National (older) | 4,109 | 0.2 MB |
| `in` | International Labor Statistics | 3,930 | 0.2 MB |
| `jt` | Job Openings and Labor Turnover Survey | 2,060 | 0.2 MB |
| `gg` | Green Goods and Services (discontinued) | 1,644 | 0.1 MB |
| `ec` | Employment Cost Index | 851 | tiny |
| `eb` | Employee Benefits Survey | 810 | tiny |
| `pr` | Major Sector Productivity and Costs | 282 | tiny |
| `jl` | JOLTS (older) | 228 | tiny |
| `bp` | Collective Bargaining, Private Sector | 95 | tiny |
| `li` | Department Store Inventory Price Index | 27 | tiny |
| `bg` | Collective Bargaining, State and Local Government | 25 | tiny |

Two things stand out. First, **`nw` is 91 percent of tier 2 and larger than all of
tier 1 combined.** Second, the heavily-used untitled programs are trivially small:
JOLTS is 2,060 series, major-sector productivity is 282, ECI is 851. Synthesizing
titles for those is a few hours of work covering most of the demand.

### Tier 3: case-routed dimension cubes (10 programs, ~162 million series, 11.8 GB)

The marker is a `case_code` column, which routes a single 6-character code into
whichever dimension column that case selects. Schema is effectively variable per row,
and lookups use composite keys such as `(case_code, category_code)`.

| Program | Name | Series | Size |
|---|---|---|---|
| `cb` | Injuries and Illnesses, Characteristics | ~53,100,000 | 3698.8 MB |
| `ca` | Injuries and Illnesses, Characteristics | ~52,400,000 | 4299.9 MB |
| `cs` | Injuries and Illnesses, Characteristics | ~29,000,000 | 2016.8 MB |
| `ch` | Injuries and Illnesses, Characteristics | 20,224,747 | 1543.0 MB |
| `fw` | Census of Fatal Occupational Injuries | 4,792,840 | 342.8 MB |
| `fi` | Census of Fatal Occupational Injuries | 987,667 | 78.2 MB |
| `fa` | Census of Fatal Occupational Injuries | 492,219 | 35.2 MB |
| `cd` | Injuries and Illnesses, Characteristics | 392,592 | 22.5 MB |
| `hc` | Injuries and Illnesses, Characteristics | 221,146 | 14.6 MB |
| `cf` | Census of Fatal Occupational Injuries, 1992-2002 | 98,623 | 5.1 MB |

`ca`, `cb`, and `cs` are estimated from 4 MB samples taken from the middle of each file
(average line width 73 to 86 bytes, stable, so the estimates are good to within a few
percent). The rest are exact counts.

Every tier-3 program is Injuries, Illnesses, and Fatalities case-characteristics data.
Sample decode of `CAULEX7145XX9S106`: median DART days, length of service not
reported, by detailed source of injury = Screwdrivers, private industry, California,
2024. The cross-tabs are legitimate statistics that nobody arrives at by typing words
into a search box.

## Scope decision, final

**Tier 1 in full including OEWS. Tier 2 except `nw`. Tier 3 excluded entirely.**

| | Programs | Series | Raw |
|---|---|---|---|
| Tier 1 (native titles) | 30 | 8,287,846 | 1,579.9 MB |
| Tier 2 minus `nw` | 24 | 1,192,148 | 74.7 MB |
| **Total scope** | **54** | **9,479,994** | **1.62 GB** |

Excluded: tier 3 (10 programs, ~162 M series, 11.8 GB) and `nw` (12.5 M series,
1.2 GB).

Rationale for the two large calls:

- **Keep `oe`.** OEWS is 63.5 percent of the index but it is the cheapest data in the
  corpus to include: native titles, zero synthesis, and no alternative source indexes
  it. Occupational wages by area is plausibly the most common Data Finder query. It was
  briefly cut on raw byte size, which is the one cost Parquet actually solves (1203 MB
  raw compresses to 33 MB).
- **Drop `nw`.** Opposite profile. 12.5 M series requiring synthesis, low search
  demand, and it would have been 57 percent of the index on its own.

Injuries and illnesses remain covered through tier 1 `is` (891,324) and tier 2 `ii`,
`hs`, `sh`, `si`. Only case-characteristics cross-tabs are absent.

Deferred: whether excluded programs should still be ID-resolvable (so pasting
`CAULEX7145XX9S106` returns something) or absent entirely. Current preference is absent;
revisit if lookup misses matter in practice.

## Program families: current versus discontinued twins

The tier split does not track subject matter. Many programs appear twice under nearly
identical names because BLS publishes the current dataset and its frozen predecessor as
separate programs. The 2003 reclassification from SIC to NAICS industry codes generated
most of these pairs. Tier membership mostly reflects *when* a dataset was frozen, since
the older ones predate the `series_title` convention.

| Family | Current | Frozen twin(s) | Twin ends |
|---|---|---|---|
| CES, national | `ce` (→2026) | `ee` | 2003 |
| CES, state and metro | `sm` (→2026) | `sa` | 2002 |
| CPI | `cu`, `cw` (→2026) | `mu`, `mw` | 2009 |
| PPI | `wp` commodity, `pc` industry (→2026) | `nd`, `wd`, `pd` | 2003 onward |
| ECEC | `cm` (2004→2026) | `cc` | 2003 |
| ECI | `ci` (→2026) | `ec` | 2005 |
| NCS benefits | `nb` (2010→2025) | `nc`, `eb` | 2006 |
| JOLTS | `jt` (→2026) | `jl` | 2003 |
| IIF, industry | `is` (2014→2024) | `ii`, `si`, `sh`, `hs` | 2013, 2002, 2001, 1988 |

Confirmed in the documentation. `jl.txt`: "With the release of May 2003 data, SIC-based
data will no longer be produced or published." `nd.txt` names itself "PRODUCER PRICE
INDEX REVISION-DISCONTINUED SERIES (ND)". `wd.txt` is labelled "discontinued".

Two traps in this table:

- **`nd` and `pd` are both graveyards, not current PPI.** `nd` holds NAICS-era
  discontinued series and `pd` the SIC-era ones. Only 0.2 percent of `nd` and 0.1
  percent of `wd` series reach 2026, and those are recent retirements being added.
  Current PPI is `wp` and `pc`.
- **`sa` is not a variant of `sm`, it is its predecessor.** `sm` carries 100 percent of
  its series to 2026; `sa` stops at 2002.

### Live and frozen composition

Computed from `begin_year` and `end_year` across the 54 in-scope programs.

| | Programs | Series | Share |
|---|---|---|---|
| Still updating (last year ≥ 2025) | 28 | 6,565,259 | 69.3% |
| Frozen (last year 1988 to 2024) | 25 | 2,913,364 | 30.7% |

Tier and liveness are orthogonal. Tier 1 contains frozen archives (`wd`, `nd`, and
`mp`, `le` largely so), while tier 2's live membership is only three programs:

| Program | Series | Range |
|---|---|---|
| `sm` | 22,927 | 1939–2026 |
| `jt` | 2,060 | 2000–2026 |
| `pr` | 282 | 1947–2026 |

**This substantially reduces the tier-2 workload.** Only those three need title templates
for live data, totalling 25,269 series. The other 21 tier-2 programs (1,166,879 series)
are immutable: synthesize their titles once, cache permanently, and never re-fetch. The
daily refresh only has to touch the 28 live programs.

It also means the index needs a `status` and `last_year` field, and search must rank
live series above frozen ones. A query for "state manufacturing employment" should not
surface 2002 SIC-era `sa` series above current `sm` ones.

## Value proposition against DBnomics

At this scope, 27 of the 54 programs (2,085,545 series) already exist on DBnomics and 27
do not (7,394,449 series, of which `oe` is 6,023,970 and `ii` is 864,870). Coverage alone
is therefore a real but narrow argument. The stronger argument is freshness.

`indexed_at` pulled from the DBnomics API on 2026-08-11:

| Dataset | Last indexed | Stale by |
|---|---|---|
| `tu` | 2025-06-27 | 13.5 months |
| `cx` | 2025-12-20 | 7.7 months |
| `is` | 2026-01-23 | 6.6 months |
| `sm` | 2026-01-28 | 6.5 months |
| `la` | 2026-02-07 | 6.1 months |
| `bd` | 2026-02-27 | 5.4 months |
| `ln` | 2026-03-07 | 5.1 months |
| `ce` | 2026-03-12 | 5.0 months |
| `cu` | 2026-03-14 | 4.9 months |
| `jt` | 2026-03-14 | 4.9 months |

Not one is current, and the drift runs both directions. DBnomics `ln` carries 67,741
series against 68,630 live, so it is **missing 889**. Its `sm` carries 23,876 against
22,927 live, so it is **serving 949 series BLS has since deleted**, unflagged, almost
certainly the January 2026 CES benchmark discontinuation. A `find_bls()` backed by that
both misses valid IDs and returns dead ones.

Summary of the differentiators:

1. **Currency.** Daily refresh against 5-to-13-month staleness.
2. **Unique coverage.** OEWS in particular, which nothing else indexes.
3. **Title fidelity.** DBnomics constructs names mechanically and it shows:
   `CES3000000003` renders as "AVERAGE HOURLY EARNINGS OF ALL EMPLOYEES – Manufacturing
   – Seasonally Adjusted – Manufacturing". Native `series_title` is cleaner.
4. **Lifecycle tracking.** Recording first-seen and last-seen dates per series. Nobody
   does this, and the `sm` evidence shows it matters.

## Measured build economics

All figures below are measured on this machine (R 4.5.3, arrow 25.0.0, duckdb 1.5.4.3,
Python sqlite3 with FTS5), not estimated, except where marked.

**Ingest**, measured over all 30 tier-1 programs:

- Download plus parse plus bind of 1,579.9 MB across 30 files: **1.2 minutes**.
- `data.table::fread` of the 1203 MB `oe.series` alone: **26 seconds**.
- A full cold rebuild of the whole 1.62 GB scope should run in roughly 5 minutes,
  comfortably inside one GitHub Actions job (14 GB disk, 7 GB RAM). No streaming or
  matrix-sharding needed once tier 3 and `nw` are gone.

**Parquet**, measured on the real tier-1 table (8,287,846 rows; columns `program`,
`series_id`, `series_title`, `begin_year`, `end_year`):

| Artifact | Size |
|---|---|
| Raw `.series` inputs | 1,579.9 MB |
| Parquet, zstd level 9 | **42.4 MB** |
| Parquet, zstd level 19 | 32.1 MB |
| Full 15-column OEWS table alone, zstd-9 | 33.1 MB |

Extrapolated to the full 9,479,994-row scope: **roughly 49 MB at zstd-9**.

Two non-obvious compression findings:

- **Titles are nearly unique**, 5,955,720 distinct out of 6,023,970 in OEWS, so
  dictionary encoding contributes almost nothing. The 36x reduction comes from zstd
  matching repeated substrings across adjacent rows.
- **Sorting by title makes it worse**, 61.0 MB against 33.1 MB. BLS delivery order is
  already area-major, which groups similar titles while keeping the code columns
  monotonic. **Preserve the delivered row order.**

**Search index**, measured over all 8,287,846 tier-1 titles (mean 111.2 characters):

| Variant | Size | Phrase queries | Query time |
|---|---|---|---|
| SQLite table with stored titles + FTS5 external content | ~1.9 GB (est) | yes | sub-ms |
| FTS5 contentless, `detail=full` | **464.6 MB** | yes | 1.7 ms |
| FTS5 contentless, `detail=column` | 341.6 MB (OEWS-scaled) | no | 1.2 ms |
| FTS5 contentless, `detail=none` | **209.9 MB** | no | 1.6 ms |

Build time for the 8.3 M-row FTS5 index: **36 seconds**. Measured directly on OEWS, a
stored-content SQLite came to 1,460.1 MB for 6.02 M rows, of which the FTS5 index was
only 355.3 MB and the stored text and id index were the other 1,110.2 MB.

Extrapolated to full scope: **~531 MB** contentless `detail=full`, **~2.1 GB** with
stored content.

## Infrastructure and cost

The measurements collapse the earlier design. Two artifacts, no always-on server.

**Build.** GitHub Actions, daily, one job. Conditional on `ETag` and `Last-Modified`,
which `download.bls.gov` supplies, so unchanged programs are skipped. Public repo means
free minutes. Roughly 5 minutes per full rebuild.

**Store.** Cloudflare R2 with a public custom domain:

- `series.parquet`, ~49 MB, the canonical artifact, in BLS delivery order.
- `search.sqlite`, ~2.1 GB, stored titles plus FTS5 external content.

R2 is chosen for zero egress fees. Mirror the Parquet to a GitHub Release or Hugging
Face dataset for dated, pinnable provenance.

**Site.** Cloudflare Pages, fully static. Search runs client-side against
`search.sqlite` over HTTP range requests via `sql.js-httpvfs`. File size is not a
download; the browser fetches only the b-tree pages a query touches, typically tens of
kilobytes. Stored content is preferred over contentless here because it returns titles
in one round trip, and the extra 1.5 GB costs about two cents a month.

**Programmatic access needs no API at all.** This is the significant revision. At 49 MB,
`epidatatools::find_bls()` can download and cache the Parquet once and query it locally.
Measured with DuckDB against the 42.4 MB tier-1 file:

- `count(*)` over 8.29 M rows: 0.01 s
- two-predicate `ILIKE` returning 25 rows: 0.53 s
- single `ILIKE` full count: 1.05 s

Sub-second local search over the whole corpus, no server, no cold start, no rate limit,
and it works offline after first fetch. A hosted JSON endpoint (Cloudflare Worker)
becomes optional, worth adding only for non-R consumers.

**Cost.**

| Item | Usage | Cost |
|---|---|---|
| R2 storage | ~2.15 GB | free tier is 10 GB, else $0.03/mo |
| R2 egress | any | $0 |
| R2 class B reads | ~20-50 range requests/search | free to ~10 M/mo, then $0.36/M |
| Cloudflare Pages | static site | $0 |
| GitHub Actions | ~5 min/day, public repo | $0 |
| **Total** | | **$0/mo, with $0.03/mo as the realistic ceiling** |

The free tier supports roughly 200,000 to 500,000 searches per month before any charge.

## Retrievability defines the scope, and the pipeline is stateless

The index is only useful for series whose values a user can actually obtain. Tested
against the BLS public API v1 on 2026-08-11, that criterion maps exactly onto presence
in the current `.series` file.

| Series | In current `.series`? | API result |
|---|---|---|
| `CES3000000003` (live) | yes | 31 points, 2024–2026 |
| `SAS0100000000001` (frozen 2002) | yes | 36 points, 2000–2002 |
| `EES00000001` (frozen 2003) | yes | 28 points, 2001–2003 |
| `MUSR0000SA0` (frozen 1997) | yes | 36 points, 1995–1997 |
| `JLU00000000HIL` (frozen 2003) | yes | 28 points, 2001–2003 |
| `SMS30000006054000001` (deleted) | **no** | **"Series does not exist"** |
| `SMU01000003231310001` (deleted) | **no** | **"Series does not exist"** |

Three conclusions.

**Frozen is not the same as unavailable, so frozen programs belong in the index.** The
API serves discontinued SIC-era series exactly like current ones, returning the last
three years of each series' own data rather than the last three calendar years. The
`.series` end dates match the API's final data point precisely (`SAS0100000000001` ends
2002 M12 in both). All frozen programs also still ship `.data` files, 81 of them for
`ee` and 108 for `sa`.

**Deleted series are genuinely dead and must be excluded.** Diffing the DBnomics `sm`
snapshot from 2026-01-28 against today's file yields **966 series** that BLS has since
removed. Every one tested returns "Series does not exist" from the API. There is no
archive dataset holding them, since `sa` has been frozen since 2002.

**Therefore the pipeline stays stateless.** The current `.series` file is precisely the
API's contract surface: presence in it is equivalent to retrievability. An index that
mirrors today's files is definitionally correct, and needs no diffing, no persistent
state store, and no `first_seen` / `last_seen` columns. A rebuild from scratch is a pure
function of today's BLS files.

This also sharpens the DBnomics comparison. Its `sm` dataset currently offers 966 series
that cannot be downloaded from BLS at all. A user who searches it, finds an ID, and
calls the API gets nothing back.

Lifecycle tracking is therefore **dropped**, not deferred, and it should be removed from
the list of differentiators; currency, OEWS coverage, and title fidelity carry that
argument on their own. Dated snapshots of the Parquet remain available as cheap
insurance for debugging the pipeline itself, but they serve no product purpose and are
not part of v1.

## Artifact schemas

Two artifacts, split by access pattern. Neither carries lifecycle state.

`series.parquet`, canonical, roughly 60 to 80 MB:

```
program, survey_name, series_id, series_title, title_source ("native"|"synthesized"),
seasonal, begin_year, begin_period, end_year, end_period, status ("live"|"frozen"),
footnote_codes, dimensions MAP(VARCHAR,VARCHAR), dimension_labels MAP(VARCHAR,VARCHAR)
```

The `dimensions` map exists because the 54 programs have irreconcilable schemas: `ce`
has 4 dimension columns, `oe` has 8, `kv` has 14. A wide union would be mostly null and
would change shape whenever BLS adds a program. Dimension codes are nearly free to
store: measured on OEWS, `series_id` plus `series_title` alone was 32.3 MB and the full
15-column table 33.1 MB, because codes are low-cardinality and dictionary-encode almost
perfectly.

`search.sqlite`, derived and non-authoritative, roughly 2.1 GB:

```sql
CREATE TABLE series (rowid INTEGER PRIMARY KEY, series_id TEXT, series_title TEXT,
                     program TEXT, status TEXT, end_year INTEGER);
CREATE INDEX idx_sid ON series(series_id);
CREATE VIRTUAL TABLE ftitle USING fts5(series_title, content='series',
                                       content_rowid='rowid');
```

Display fields only. Detail views read the rest from the Parquet.

## Remaining implementation unknowns

- **Tier-2 title templates.** 24 per-program synthesis rules, none written. Smaller than
  it first appeared: only `sm`, `jt`, and `pr` (25,269 series) cover live data and need
  ongoing maintenance. The remaining 21 programs (1,166,879 series) are frozen, so their
  templates run once and the output is cached permanently.
- **Relevance ranking.** Two distinct problems. OEWS is 63.5 percent of the index and
  will swamp generic queries. Separately, 30.7 percent of the corpus is frozen history,
  and current series must outrank their discontinued twins by default.
- **Schema normalization.** 11 programs need per-program parse overrides rather than
  header-driven parsing, and `kv` has no date columns to normalize against.
- **Refresh partitioning.** The daily job only needs the 28 live programs (roughly
  1.5 GB). The 25 frozen ones can be fetched once and pinned, which cuts steady-state
  ingest substantially.
- **Search engine parity.** The browser searches via FTS5 tokenized matching while
  `find_bls()` would use DuckDB `ILIKE` over the Parquet. The two will not return
  identical result sets or ordering for the same query. Either that is documented as
  acceptable, or `find_bls()` calls a hosted endpoint over the same FTS5 index, which
  reintroduces the Worker that local Parquet search otherwise makes unnecessary.

## Parsing gotchas found during inventory

- **11 of 54 in-scope programs have header anomalies.** Audited by comparing the header
  column count to the first data row:

  | Program | Header cols | Row cols | Problem |
  |---|---|---|---|
  | `cc` | 19 | 10 | header and first data row concatenated, no newline between them |
  | `eb`, `ec`, `ee`, `gp`, `hs`, `pd`, `sa`, `sh`, `si` | n | n+1 | undeclared trailing footnote column |
  | `kv` | 18 | 18 | **no `begin_year` or `end_year` columns at all** |

  All ten mismatching programs are frozen tier-2 archives, so the sloppier schemas
  cluster in the SIC-era datasets. `kv` is live tier 1 and simply carries no date range,
  so any pipeline assuming universal date columns will drop or corrupt it.

- **`hs.series` is the worst case and cost a first-pass error.** Its 9-column header
  against 11-column rows shifted `begin_year` from field 6 to field 7 and `end_year`
  from 8 to 9. Parsing by header position silently produced all-`NA` years. Correct
  range is 18,762 series spanning 1976 to 1988. Validate that parsed years are
  plausible rather than trusting the header.
- **Range requests are honored inconsistently.** `accept-ranges: bytes` is advertised
  and works on the largest files (`ca`, `cb`, `cs`), but several mid-size files return
  the whole body regardless of the `Range` header. Do not rely on partial reads for
  sampling.
- **No gzip on the wire.** `Accept-Encoding: gzip` is ignored; `content-length` is
  identical either way. `compressed/bin/` holds only a 1997 gzip binary, and
  per-program tarballs are inconsistent (`ec.tar` exists, `ca.tar` is a 404). Full
  uncompressed transfer is the only ingest path.
- **`series_id` columns are space-padded** in many programs (`ce`, `oe`, `ca`, `jt`,
  `sm`, `pr`), so trim before joining or comparing.
- **Column alignment is positionally fragile.** Tier-3 rows carry 20-plus consecutive
  empty tab-delimited fields; an off-by-one silently attributes a code to the wrong
  dimension. Parse strictly by header position, and validate that every decoded code
  exists in its lookup table.

## Conclusion

Worth building, and cheaper than expected. The scope is 54 programs and 9,479,994
series: native BLS `series_title` where it exists, mechanically synthesized titles where
it does not, refreshed daily.

The measurements changed the shape of the answer. 1.62 GB of raw metadata compresses to
a **49 MB Parquet file**, which is small enough that the programmatic use case needs no
server at all: `epidatatools::find_bls()` downloads and caches it, then searches locally
in under a second. The web page is a static SQLite FTS5 index read over HTTP range
requests. Total infrastructure is two files on object storage and a daily GitHub Action,
running at $0 per month.

Against the surveyed alternatives, the pitch is currency and coverage: the sampled
DBnomics datasets were 5 to 13 months stale on 2026-08-11, with drift in both directions;
BLS Series Lookup offers useful browser discovery for 11 programs, but does not include
OEWS or document an automatic refresh pipeline.

## Sources

- [BLS Data Finder maintenance notice](https://www.bls.gov/bls/data-query-not-available.htm)
- [BLS Data API features](https://www.bls.gov/bls/api_features.htm)
- [BLS Data Finder features](https://www.bls.gov/bls/dqt_feature.htm)
- [BLS series ID formats](https://www.bls.gov/help/hlpforma.htm)
- [BLS Series Report](https://data.bls.gov/series-report)
- [DBnomics BLS provider](https://db.nomics.world/BLS)
- [DBnomics BLS fetcher](https://git.nomics.world/dbnomics-fetchers/bls-fetcher)
- [BLS Series Lookup](https://prestonmui.github.io/bls-series-lookup/) and [source repository](https://github.com/PrestonMui/bls-series-lookup) (checked 2026-09-25)
- [FRED](https://fred.stlouisfed.org/)
- [blscrapeR](https://github.com/keberwein/blscrapeR)
- [BLSloadR](https://schmidtdetr.github.io/BLSloadR/)
- [tidyusmacro getBLSFiles](https://www.mikekonczal.com/tidyusmacro/reference/getBLSFiles.html)
- [SAE publication changes, January 2026](https://www.bls.gov/sae/notices/2026/notice-of-publication-changes-with-the-release-of-january-2026-data.htm)
