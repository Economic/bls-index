# Reference client: speed and first results (2026-10-21)

Measurements of `examples/find_bls.R` (task 1.10) on the full 8,315,248-row catalog,
built from the 2026-10-20 download. R 4.5.3, `arrow` 25.0.1, on the maintainer's
workstation, querying a cached local catalog.

## Speed and memory

| Search | Time | Peak memory |
|---|---|---|
| "quits" | 1.0 s | |
| "registered nurses" | 1.6 s | 1.1 GB |
| "unemployment rate" | 1.6 s | |
| "CPI" | 1.0 s | |
| "OEWS" (6,023,970 matches) | 1.5 s | 2.1 GB |
| "quits", `survey = "ln"` | 0.2 s | |
| First call: copy and verify the 33 MB catalog | 1.8 s | |

Starting R and loading the packages alone uses 0.13 GB. The first working version took
2.8–10.5 s per search and peaked at 8.4 GB. Two changes fixed that:
- survey names and aliases are matched against the 33-program table instead of 8.3
  million rows
- the matches are scanned once and kept in `arrow` memory; counts by rank and title
  length then show where the first 1,000 rows end, so only those rows (plus ties) reach R

`survey =` already skips other programs' data through the Parquet statistics, so no
row-group change was needed.

## First 20 results

The sort ranks rows by how many search words match the title or an alias, then by
title length, title and series ID (`design.md`). It puts the headline series first for
"unemployment rate" and "average hourly earnings manufacturing". Within a survey, short
titles often mean small places or industries ("CPI" starts with Pacific; "OEWS" with
Ohio). More words narrow it: "CPI all items U.S. city average" lists `CUSR0000SA0` first,
and "JOLTS quits total nonfarm total US" lists `JTS000000000000000QUR` first.

### "unemployment rate"


**Message:** 13,163 matches; showing the first 1,000. Narrow the search, or use `limit = Inf`. By survey: la 8,536, ln 4,197, fm 240, kv 138, jt 52. 

**Time:** 2.4 s.

| # | Series ID | Program | Seasonal | Title |
|---|---|---|---|---|
| 1 | `LNS14000000` | ln | SA | (Seas) Unemployment Rate |
| 2 | `LNS14000000Q` | ln | SA | (Seas) Unemployment Rate |
| 3 | `LNU04000000` | ln | NSA | (Unadj) Unemployment Rate |
| 4 | `LNU04000000Q` | ln | NSA | (Unadj) Unemployment Rate |
| 5 | `LASST190000000000003` | la | SA | Unemployment Rate: Iowa (S) |
| 6 | `LAUST190000000000003` | la | NSA | Unemployment Rate: Iowa (U) |
| 7 | `LASST390000000000003` | la | SA | Unemployment Rate: Ohio (S) |
| 8 | `LAUST390000000000003` | la | NSA | Unemployment Rate: Ohio (U) |
| 9 | `LASST490000000000003` | la | SA | Unemployment Rate: Utah (S) |
| 10 | `LAUST490000000000003` | la | NSA | Unemployment Rate: Utah (U) |
| 11 | `KVU0400000000000058` | kv | NSA | Unemployment rate - Veterans |
| 12 | `LASST160000000000003` | la | SA | Unemployment Rate: Idaho (S) |
| 13 | `LAUST160000000000003` | la | NSA | Unemployment Rate: Idaho (U) |
| 14 | `LASST230000000000003` | la | SA | Unemployment Rate: Maine (S) |
| 15 | `LAUST230000000000003` | la | NSA | Unemployment Rate: Maine (U) |
| 16 | `LASST480000000000003` | la | SA | Unemployment Rate: Texas (S) |
| 17 | `LAUST480000000000003` | la | NSA | Unemployment Rate: Texas (U) |
| 18 | `LASST020000000000003` | la | SA | Unemployment Rate: Alaska (S) |
| 19 | `LAUST020000000000003` | la | NSA | Unemployment Rate: Alaska (U) |
| 20 | `LASST150000000000003` | la | SA | Unemployment Rate: Hawaii (S) |

### "consumer price index"


**Message:** 16,202 matches; showing the first 1,000. Narrow the search, or use `limit = Inf`. By survey: cu 8,104, cw 7,868, wp 84, wd 65, su 29, pc 22, nd 20, ei 10. 

**Time:** 2.52 s.

| # | Series ID | Program | Seasonal | Title |
|---|---|---|---|---|
| 1 | `CUUR0490SAF1` | cu | NSA | Food in Pacific, all urban consumers, not seasonally adjusted |
| 2 | `CUUS0490SAF1` | cu | NSA | Food in Pacific, all urban consumers, not seasonally adjusted |
| 3 | `CUUR0480SAF1` | cu | NSA | Food in Mountain, all urban consumers, not seasonally adjusted |
| 4 | `CUUS0480SAF1` | cu | NSA | Food in Mountain, all urban consumers, not seasonally adjusted |
| 5 | `CUUR0490SA0E` | cu | NSA | Energy in Pacific, all urban consumers, not seasonally adjusted |
| 6 | `CUUS0490SA0E` | cu | NSA | Energy in Pacific, all urban consumers, not seasonally adjusted |
| 7 | `CUUR0490SAA` | cu | NSA | Apparel in Pacific, all urban consumers, not seasonally adjusted |
| 8 | `CUUS0490SAA` | cu | NSA | Apparel in Pacific, all urban consumers, not seasonally adjusted |
| 9 | `CUUR0480SA0E` | cu | NSA | Energy in Mountain, all urban consumers, not seasonally adjusted |
| 10 | `CUUS0480SA0E` | cu | NSA | Energy in Mountain, all urban consumers, not seasonally adjusted |
| 11 | `CUUR0400SAF1` | cu | NSA | Food in West urban, all urban consumers, not seasonally adjusted |
| 12 | `CUUS0400SAF1` | cu | NSA | Food in West urban, all urban consumers, not seasonally adjusted |
| 13 | `CUUR0490SAH` | cu | NSA | Housing in Pacific, all urban consumers, not seasonally adjusted |
| 14 | `CUUS0490SAH` | cu | NSA | Housing in Pacific, all urban consumers, not seasonally adjusted |
| 15 | `CUUR0490SAH1` | cu | NSA | Shelter in Pacific, all urban consumers, not seasonally adjusted |
| 16 | `CUUS0490SAH1` | cu | NSA | Shelter in Pacific, all urban consumers, not seasonally adjusted |
| 17 | `CUUR0480SAA` | cu | NSA | Apparel in Mountain, all urban consumers, not seasonally adjusted |
| 18 | `CUUS0480SAA` | cu | NSA | Apparel in Mountain, all urban consumers, not seasonally adjusted |
| 19 | `CUUR0490SAD` | cu | NSA | Durables in Pacific, all urban consumers, not seasonally adjusted |
| 20 | `CUUS0490SAD` | cu | NSA | Durables in Pacific, all urban consumers, not seasonally adjusted |

### "CPI"


**Message:** 16,119 matches; showing the first 1,000. Narrow the search, or use `limit = Inf`. By survey: cu 8,104, cw 7,868, le 118, su 29. 

**Time:** 0.97 s.

| # | Series ID | Program | Seasonal | Title |
|---|---|---|---|---|
| 1 | `CUUR0490SAF1` | cu | NSA | Food in Pacific, all urban consumers, not seasonally adjusted |
| 2 | `CUUS0490SAF1` | cu | NSA | Food in Pacific, all urban consumers, not seasonally adjusted |
| 3 | `CUUR0480SAF1` | cu | NSA | Food in Mountain, all urban consumers, not seasonally adjusted |
| 4 | `CUUS0480SAF1` | cu | NSA | Food in Mountain, all urban consumers, not seasonally adjusted |
| 5 | `CUUR0490SA0E` | cu | NSA | Energy in Pacific, all urban consumers, not seasonally adjusted |
| 6 | `CUUS0490SA0E` | cu | NSA | Energy in Pacific, all urban consumers, not seasonally adjusted |
| 7 | `CUUR0490SAA` | cu | NSA | Apparel in Pacific, all urban consumers, not seasonally adjusted |
| 8 | `CUUS0490SAA` | cu | NSA | Apparel in Pacific, all urban consumers, not seasonally adjusted |
| 9 | `CUUR0480SA0E` | cu | NSA | Energy in Mountain, all urban consumers, not seasonally adjusted |
| 10 | `CUUS0480SA0E` | cu | NSA | Energy in Mountain, all urban consumers, not seasonally adjusted |
| 11 | `CUUR0400SAF1` | cu | NSA | Food in West urban, all urban consumers, not seasonally adjusted |
| 12 | `CUUS0400SAF1` | cu | NSA | Food in West urban, all urban consumers, not seasonally adjusted |
| 13 | `CUUR0490SAH` | cu | NSA | Housing in Pacific, all urban consumers, not seasonally adjusted |
| 14 | `CUUS0490SAH` | cu | NSA | Housing in Pacific, all urban consumers, not seasonally adjusted |
| 15 | `CUUR0490SAH1` | cu | NSA | Shelter in Pacific, all urban consumers, not seasonally adjusted |
| 16 | `CUUS0490SAH1` | cu | NSA | Shelter in Pacific, all urban consumers, not seasonally adjusted |
| 17 | `CUUR0480SAA` | cu | NSA | Apparel in Mountain, all urban consumers, not seasonally adjusted |
| 18 | `CUUS0480SAA` | cu | NSA | Apparel in Mountain, all urban consumers, not seasonally adjusted |
| 19 | `CUUR0490SAD` | cu | NSA | Durables in Pacific, all urban consumers, not seasonally adjusted |
| 20 | `CUUS0490SAD` | cu | NSA | Durables in Pacific, all urban consumers, not seasonally adjusted |

### "JOLTS quits"


**Message:** (none)

**Time:** 1.54 s.

| # | Series ID | Program | Seasonal | Title |
|---|---|---|---|---|
| 1 | `JTS910000000000000QUR` | jt | SA | Data element: Quits; Rate/level: Rate; Industry: Federal; State: Total US; Area: All areas; Size class: All size classes |
| 2 | `JTU910000000000000QUR` | jt | NSA | Data element: Quits; Rate/level: Rate; Industry: Federal; State: Total US; Area: All areas; Size class: All size classes |
| 3 | `JTS000000190000000QUR` | jt | SA | Data element: Quits; Rate/level: Rate; Industry: Total nonfarm; State: Iowa; Area: All areas; Size class: All size classes |
| 4 | `JTU000000190000000QUR` | jt | NSA | Data element: Quits; Rate/level: Rate; Industry: Total nonfarm; State: Iowa; Area: All areas; Size class: All size classes |
| 5 | `JTS000000390000000QUR` | jt | SA | Data element: Quits; Rate/level: Rate; Industry: Total nonfarm; State: Ohio; Area: All areas; Size class: All size classes |
| 6 | `JTU000000390000000QUR` | jt | NSA | Data element: Quits; Rate/level: Rate; Industry: Total nonfarm; State: Ohio; Area: All areas; Size class: All size classes |
| 7 | `JTS000000490000000QUR` | jt | SA | Data element: Quits; Rate/level: Rate; Industry: Total nonfarm; State: Utah; Area: All areas; Size class: All size classes |
| 8 | `JTU000000490000000QUR` | jt | NSA | Data element: Quits; Rate/level: Rate; Industry: Total nonfarm; State: Utah; Area: All areas; Size class: All size classes |
| 9 | `JTS900000000000000QUR` | jt | SA | Data element: Quits; Rate/level: Rate; Industry: Government; State: Total US; Area: All areas; Size class: All size classes |
| 10 | `JTU900000000000000QUR` | jt | NSA | Data element: Quits; Rate/level: Rate; Industry: Government; State: Total US; Area: All areas; Size class: All size classes |
| 11 | `JTS000000160000000QUR` | jt | SA | Data element: Quits; Rate/level: Rate; Industry: Total nonfarm; State: Idaho; Area: All areas; Size class: All size classes |
| 12 | `JTU000000160000000QUR` | jt | NSA | Data element: Quits; Rate/level: Rate; Industry: Total nonfarm; State: Idaho; Area: All areas; Size class: All size classes |
| 13 | `JTS000000230000000QUR` | jt | SA | Data element: Quits; Rate/level: Rate; Industry: Total nonfarm; State: Maine; Area: All areas; Size class: All size classes |
| 14 | `JTU000000230000000QUR` | jt | NSA | Data element: Quits; Rate/level: Rate; Industry: Total nonfarm; State: Maine; Area: All areas; Size class: All size classes |
| 15 | `JTS000000480000000QUR` | jt | SA | Data element: Quits; Rate/level: Rate; Industry: Total nonfarm; State: Texas; Area: All areas; Size class: All size classes |
| 16 | `JTU000000480000000QUR` | jt | NSA | Data element: Quits; Rate/level: Rate; Industry: Total nonfarm; State: Texas; Area: All areas; Size class: All size classes |
| 17 | `JTS510000000000000QUR` | jt | SA | Data element: Quits; Rate/level: Rate; Industry: Information; State: Total US; Area: All areas; Size class: All size classes |
| 18 | `JTU510000000000000QUR` | jt | NSA | Data element: Quits; Rate/level: Rate; Industry: Information; State: Total US; Area: All areas; Size class: All size classes |
| 19 | `JTS000000020000000QUR` | jt | SA | Data element: Quits; Rate/level: Rate; Industry: Total nonfarm; State: Alaska; Area: All areas; Size class: All size classes |
| 20 | `JTU000000020000000QUR` | jt | NSA | Data element: Quits; Rate/level: Rate; Industry: Total nonfarm; State: Alaska; Area: All areas; Size class: All size classes |

### "registered nurses"


**Message:** 19,686 matches; showing the first 1,000. Narrow the search, or use `limit = Inf`. By survey: oe 12,674, wm 6,206, nb 305, or 254, ep 166, cm 54, ln 17, le 10. 

**Time:** 1.56 s.

| # | Series ID | Program | Seasonal | Title |
|---|---|---|---|---|
| 1 | `EPU291141220000` | ep | NSA | Registered nurses in Utilities |
| 2 | `EPU291141221000` | ep | NSA | Registered nurses in Utilities |
| 3 | `EPU291141510000` | ep | NSA | Registered nurses in Information |
| 4 | `EPU29114144450` | ep | NSA | Registered nurses in Retail trade |
| 5 | `EPU291141721000` | ep | NSA | Registered nurses in Accommodation |
| 6 | `EPU29114131330` | ep | NSA | Registered nurses in Manufacturing |
| 7 | `EPU291141541100` | ep | NSA | Registered nurses in Legal services |
| 8 | `EPU291141491000` | ep | NSA | Registered nurses in Postal service |
| 9 | `LNU02038331` | ln | NSA | (unadj) Employed - Registered nurses |
| 10 | `EPU291141420000` | ep | NSA | Registered nurses in Wholesale trade |
| 11 | `EPU291141624000` | ep | NSA | Registered nurses in Social assistance |
| 12 | `EPU291141481000` | ep | NSA | Registered nurses in Air transportation |
| 13 | `EPU291141621910` | ep | NSA | Registered nurses in Ambulance services |
| 14 | `EPU291141910000` | ep | NSA | Registered nurses in Federal government |
| 15 | `EPU291141311000` | ep | NSA | Registered nurses in Food manufacturing |
| 16 | `EPU2911416220P0` | ep | NSA | Registered nurses in Hospitals; private |
| 17 | `EPU291141524100` | ep | NSA | Registered nurses in Insurance carriers |
| 18 | `EPU291141814000` | ep | NSA | Registered nurses in Private households |
| 19 | `EPU291141561300` | ep | NSA | Registered nurses in Employment services |
| 20 | `EPU291141621200` | ep | NSA | Registered nurses in Offices of dentists |

### "average hourly earnings manufacturing"


**Message:** 2,138 matches; showing the first 1,000. Narrow the search, or use `limit = Inf`. By survey: ce 1,715, sm 423. 

**Time:** 2.69 s.

| # | Series ID | Program | Seasonal | Title |
|---|---|---|---|---|
| 1 | `CES3000000003` | ce | SA | Average hourly earnings of all employees, manufacturing, seasonally adjusted |
| 2 | `CEU3000000003` | ce | NSA | Average hourly earnings of all employees, manufacturing, not seasonally adjusted |
| 3 | `CES3231100003` | ce | SA | Average hourly earnings of all employees, food manufacturing, seasonally adjusted |
| 4 | `CES3133995003` | ce | SA | Average hourly earnings of all employees, sign manufacturing, seasonally adjusted |
| 5 | `CES3232200003` | ce | SA | Average hourly earnings of all employees, paper manufacturing, seasonally adjusted |
| 6 | `CES3231500003` | ce | SA | Average hourly earnings of all employees, apparel manufacturing, seasonally adjusted |
| 7 | `CES3133641103` | ce | SA | Average hourly earnings of all employees, aircraft manufacturing, seasonally adjusted |
| 8 | `CES3232500003` | ce | SA | Average hourly earnings of all employees, chemical manufacturing, seasonally adjusted |
| 9 | `CEU3231100003` | ce | NSA | Average hourly earnings of all employees, food manufacturing, not seasonally adjusted |
| 10 | `CEU3133995003` | ce | NSA | Average hourly earnings of all employees, sign manufacturing, not seasonally adjusted |
| 11 | `CES3133300003` | ce | SA | Average hourly earnings of all employees, machinery manufacturing, seasonally adjusted |
| 12 | `CEU3232200003` | ce | NSA | Average hourly earnings of all employees, paper manufacturing, not seasonally adjusted |
| 13 | `CES3231190003` | ce | SA | Average hourly earnings of all employees, other food manufacturing, seasonally adjusted |
| 14 | `CEU3231500003` | ce | NSA | Average hourly earnings of all employees, apparel manufacturing, not seasonally adjusted |
| 15 | `CES3231141003` | ce | SA | Average hourly earnings of all employees, frozen food manufacturing, seasonally adjusted |
| 16 | `CEU3133641103` | ce | NSA | Average hourly earnings of all employees, aircraft manufacturing, not seasonally adjusted |
| 17 | `CEU3232500003` | ce | NSA | Average hourly earnings of all employees, chemical manufacturing, not seasonally adjusted |
| 18 | `CES3132100003` | ce | SA | Average hourly earnings of all employees, wood product manufacturing, seasonally adjusted |
| 19 | `CES3231150003` | ce | SA | Average hourly earnings of all employees, dairy product manufacturing, seasonally adjusted |
| 20 | `CEU3133300003` | ce | NSA | Average hourly earnings of all employees, machinery manufacturing, not seasonally adjusted |

### "OEWS"


**Message:** 6,023,970 matches; showing the first 1,000. Narrow the search, or use `limit = Inf`. By survey: oe 6,023,970. 

**Time:** 1.69 s.

| # | Series ID | Program | Seasonal | Title |
|---|---|---|---|---|
| 1 | `OEUS390000000000027201101` | oe | NSA | Employment for Actors in All Industries in Ohio |
| 2 | `OEUS490000000000027201101` | oe | NSA | Employment for Actors in All Industries in Utah |
| 3 | `OEUS660000000000051301101` | oe | NSA | Employment for Bakers in All Industries in Guam |
| 4 | `OEUS190000000000051301101` | oe | NSA | Employment for Bakers in All Industries in Iowa |
| 5 | `OEUS390000000000051301101` | oe | NSA | Employment for Bakers in All Industries in Ohio |
| 6 | `OEUS490000000000051301101` | oe | NSA | Employment for Bakers in All Industries in Utah |
| 7 | `OEUS660000000000021201101` | oe | NSA | Employment for Clergy in All Industries in Guam |
| 8 | `OEUS190000000000021201101` | oe | NSA | Employment for Clergy in All Industries in Iowa |
| 9 | `OEUS390000000000021201101` | oe | NSA | Employment for Clergy in All Industries in Ohio |
| 10 | `OEUS390000000000041901201` | oe | NSA | Employment for Models in All Industries in Ohio |
| 11 | `OEUS190000000000047208201` | oe | NSA | Employment for Tapers in All Industries in Iowa |
| 12 | `OEUS390000000000047208201` | oe | NSA | Employment for Tapers in All Industries in Ohio |
| 13 | `OEUS490000000000047208201` | oe | NSA | Employment for Tapers in All Industries in Utah |
| 14 | `OEUS660000000000025304101` | oe | NSA | Employment for Tutors in All Industries in Guam |
| 15 | `OEUS190000000000025304101` | oe | NSA | Employment for Tutors in All Industries in Iowa |
| 16 | `OEUS390000000000025304101` | oe | NSA | Employment for Tutors in All Industries in Ohio |
| 17 | `OEUS490000000000025304101` | oe | NSA | Employment for Tutors in All Industries in Utah |
| 18 | `OEUS480000000000027201101` | oe | NSA | Employment for Actors in All Industries in Texas |
| 19 | `OEUS160000000000051301101` | oe | NSA | Employment for Bakers in All Industries in Idaho |
| 20 | `OEUS230000000000051301101` | oe | NSA | Employment for Bakers in All Industries in Maine |
