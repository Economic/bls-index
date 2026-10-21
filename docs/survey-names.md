# Survey names

`survey_name` holds one name per program, defined in `SURVEY_NAMES` in
`src/bls_index/scope.py`. Names were collected on 2026-10-20 from three official BLS
sources, taking each program from the first source that lists it:

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

| Program | Survey name | Source |
|---|---|---|
| `ap` | Average Price Data | help page |
| `bd` | Business Employment Dynamics | help page |
| `ce` | National Employment, Hours, and Earnings | help page |
| `ci` | Employment Cost Index | help page |
| `cm` | Employer Costs for Employee Compensation | help page |
| `cu` | Consumer Price Index - All Urban Consumers | help page |
| `cw` | Consumer Price Index - Urban Wage Earners and Clerical Workers | help page |
| `cx` | Consumer Expenditure Survey | help page (`cx.txt` returns 404) |
| `ei` | Import/Export Price Indexes | help page |
| `ep` | Employment Projections | `ep.txt` |
| `fm` | Marital and family labor force statistics (Current Population Survey - CPS) | data page |
| `ip` | Industry Productivity | help page |
| `is` | Occupational Injuries and Illnesses - industry data | help page |
| `jt` | Job Openings and Labor Turnover Survey | help page |
| `kv` | CPS Veterans Supplement | `kv.txt` |
| `la` | Local Area Unemployment Statistics | help page |
| `le` | Weekly & Hourly Earnings (Current Population Survey - CPS) | data page |
| `ln` | Labor Force Statistics (Current Population Survey - CPS) | data page |
| `lu` | Union Affiliation Data (Current Population Survey - CPS) | data page |
| `mp` | Major Sector Total Factor Productivity | help page |
| `nb` | National Benefits | help page |
| `nd` | Producer Price Index Revision - Discontinued Series | `nd.txt` (definition line) |
| `oe` | Occupational Employment and Wage Statistics | `oe.txt` |
| `or` | Occupational Requirements Survey | help page |
| `pc` | Producer Price Index Industry Data - Current Series | help page |
| `pr` | Major Sector Productivity and Costs | help page |
| `sm` | State and Area Employment, Hours, and Earnings | help page |
| `su` | Chained CPI-All Urban Consumers | help page |
| `tu` | American Time Use Survey | help page |
| `wd` | Producer Price Index - Commodity Data - discontinued | `wd.txt` |
| `wm` | Modeled Wage Estimates | help page |
| `wp` | Producer Price Index Commodity Data - Current Series | help page |
| `ws` | Work Stoppages Program | help page |

To add a program, add its name to `SURVEY_NAMES` and a row here, following the same
source order.
