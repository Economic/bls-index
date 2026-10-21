# Survey names and aliases

Each program has two fixed values, defined in `src/bls_index/scope.py`:

- `survey_name`: the official BLS name, shown to users (`SURVEY_NAMES`)
- `survey_aliases`: other names people search for, separated by `; ` (`SURVEY_ALIASES`).
  These are used for matching only.

## Survey names

Names were collected on 2026-10-20 from three official BLS sources, taking each program
from the first source that lists it:

1. **Help page:** the section headings of BLS's series ID formats page,
   <https://www.bls.gov/help/hlpforma.htm>.
2. **Data page:** the database names on "Databases, Tables & Calculators by Subject",
   <https://www.bls.gov/data/>.
3. **`.txt` file:** the title line of the program's documentation file,
   `https://download.bls.gov/pub/time.series/<program>/<program>.txt`.

Edits to the source text:
- Trailing program codes such as "(CU)" are dropped.
- Coverage qualifiers such as "(NAICS and SOC)" and "(2014 forward)" are dropped.
- The two all-capitals `.txt` titles (`ep`, `nd`) are set in title case.

## Aliases

Aliases are our choice, not BLS source text. There are three kinds:

- **Initialisms**, most of them used on BLS's own pages: for example BED, CES, ECI,
  JOLTS, LAUS, SOII, ATUS, CPI-U, and C-CPI-U.
- **Former names:** OES, the name of OEWS until 2021.
- **Informal names:**
  - "household survey" for `ln` and "establishment survey" for `ce`, the names BLS's
    monthly jobs report uses
  - CEX for `cx`, the common research abbreviation (BLS writes CE)
  - "Current Employment Statistics" for `ce`, the survey's usual name
  - "consumer price index" for `su`, whose official name abbreviates it to CPI

Some aliases are shared by several programs, because that is what a user typing them
means:
- CPI: `cu`, `cw` and `su`
- PPI: `pc`, `wp`, `nd` and `wd`

The CPS programs need no alias: their names already contain "CPS".

Clients match aliases with the same search rules as titles, described in
[`design.md`](../design.md): stemmed words matched at the start of a word. Short words
such as "CES" match only as whole words, so "CES" does not match "services" or "census".

## Table

| Program | Survey name | Source | Aliases |
|---|---|---|---|
| `ap` | Average Price Data | help page |  |
| `bd` | Business Employment Dynamics | help page | BED |
| `ce` | National Employment, Hours, and Earnings | help page | CES; Current Employment Statistics; establishment survey |
| `ci` | Employment Cost Index | help page | ECI |
| `cm` | Employer Costs for Employee Compensation | help page | ECEC |
| `cu` | Consumer Price Index - All Urban Consumers | help page | CPI; CPI-U |
| `cw` | Consumer Price Index - Urban Wage Earners and Clerical Workers | help page | CPI; CPI-W |
| `cx` | Consumer Expenditure Survey | help page (`cx.txt` returns 404) | CEX |
| `ei` | Import/Export Price Indexes | help page | MXP |
| `ep` | Employment Projections | `ep.txt` |  |
| `fm` | Marital and family labor force statistics (Current Population Survey - CPS) | data page |  |
| `ip` | Industry Productivity | help page |  |
| `is` | Occupational Injuries and Illnesses - industry data | help page | SOII |
| `jt` | Job Openings and Labor Turnover Survey | help page | JOLTS |
| `kv` | CPS Veterans Supplement | `kv.txt` |  |
| `la` | Local Area Unemployment Statistics | help page | LAUS |
| `le` | Weekly & Hourly Earnings (Current Population Survey - CPS) | data page |  |
| `ln` | Labor Force Statistics (Current Population Survey - CPS) | data page | household survey |
| `lu` | Union Affiliation Data (Current Population Survey - CPS) | data page |  |
| `mp` | Major Sector Total Factor Productivity | help page |  |
| `nb` | National Benefits | help page | NCS |
| `nd` | Producer Price Index Revision - Discontinued Series | `nd.txt` (definition line) | PPI |
| `oe` | Occupational Employment and Wage Statistics | `oe.txt` | OEWS; OES |
| `or` | Occupational Requirements Survey | help page | ORS |
| `pc` | Producer Price Index Industry Data - Current Series | help page | PPI |
| `pr` | Major Sector Productivity and Costs | help page |  |
| `sm` | State and Area Employment, Hours, and Earnings | help page | SAE |
| `su` | Chained CPI-All Urban Consumers | help page | CPI; C-CPI-U; consumer price index |
| `tu` | American Time Use Survey | help page | ATUS |
| `wd` | Producer Price Index - Commodity Data - discontinued | `wd.txt` | PPI |
| `wm` | Modeled Wage Estimates | help page | MWE |
| `wp` | Producer Price Index Commodity Data - Current Series | help page | PPI |
| `ws` | Work Stoppages Program | help page |  |

To add a program, add its name to `SURVEY_NAMES`, any aliases to `SURVEY_ALIASES`, and a
row here, following the same source order.
