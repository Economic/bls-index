"""The published program scope.

This module is the only source of scope: every build covers ``INITIAL_PROGRAMS``, and
scope changes only through a reviewed change here. Scope is never inferred from the BLS
directory listing, a failed or missing source, or the future checkpoint lists.
"""

from __future__ import annotations

# Checkpoint 1: programs whose .series files carry a native ``series_title``.
NATIVE_TITLE_PROGRAMS: tuple[str, ...] = (
    "ap", "bd", "ce", "ci", "cm", "cu", "cw", "cx", "ei", "ep",
    "fm", "ip", "is", "kv", "la", "le", "ln", "lu", "mp", "nb",
    "nd", "oe", "or", "pc", "su", "tu", "wd", "wm", "wp", "ws",
)  # fmt: skip

# Checkpoint 2: live programs without native titles; titles are synthesized from lookups.
SYNTHESIZED_TITLE_PROGRAMS: tuple[str, ...] = ("sm", "jt", "pr")

INITIAL_PROGRAMS: tuple[str, ...] = tuple(
    sorted(NATIVE_TITLE_PROGRAMS + SYNTHESIZED_TITLE_PROGRAMS)
)

# Lookup files joined to synthesize titles; must match the dimensions in
# builders.SYNTHESES. Seasonal codes map directly (S to SA, U to NSA), so the seasonal
# lookups are not downloaded.
LOOKUP_FILES: dict[str, tuple[str, ...]] = {
    "sm": ("state", "area", "supersector", "industry", "data_type"),
    "jt": ("industry", "state", "area", "sizeclass", "dataelement", "ratelevel"),
    "pr": ("sector", "class", "measure", "duration"),
}


# Each program's survey name, taken from official BLS pages; docs/survey-names.md
# records the source of each. Adding a program to scope adds its name here.
SURVEY_NAMES: dict[str, str] = {
    "ap": "Average Price Data",
    "bd": "Business Employment Dynamics",
    "ce": "National Employment, Hours, and Earnings",
    "ci": "Employment Cost Index",
    "cm": "Employer Costs for Employee Compensation",
    "cu": "Consumer Price Index - All Urban Consumers",
    "cw": "Consumer Price Index - Urban Wage Earners and Clerical Workers",
    "cx": "Consumer Expenditure Survey",
    "ei": "Import/Export Price Indexes",
    "ep": "Employment Projections",
    "fm": "Marital and family labor force statistics (Current Population Survey - CPS)",
    "ip": "Industry Productivity",
    "is": "Occupational Injuries and Illnesses - industry data",
    "jt": "Job Openings and Labor Turnover Survey",
    "kv": "CPS Veterans Supplement",
    "la": "Local Area Unemployment Statistics",
    "le": "Weekly & Hourly Earnings (Current Population Survey - CPS)",
    "ln": "Labor Force Statistics (Current Population Survey - CPS)",
    "lu": "Union Affiliation Data (Current Population Survey - CPS)",
    "mp": "Major Sector Total Factor Productivity",
    "nb": "National Benefits",
    "nd": "Producer Price Index Revision - Discontinued Series",
    "oe": "Occupational Employment and Wage Statistics",
    "or": "Occupational Requirements Survey",
    "pc": "Producer Price Index Industry Data - Current Series",
    "pr": "Major Sector Productivity and Costs",
    "sm": "State and Area Employment, Hours, and Earnings",
    "su": "Chained CPI-All Urban Consumers",
    "tu": "American Time Use Survey",
    "wd": "Producer Price Index - Commodity Data - discontinued",
    "wm": "Modeled Wage Estimates",
    "wp": "Producer Price Index Commodity Data - Current Series",
    "ws": "Work Stoppages Program",
}


# Other names people search for: initialisms, former names, and informal names. These
# are our choice, not BLS text; docs/survey-names.md gives each one's reason. Programs
# without an entry have no aliases.
SURVEY_ALIASES: dict[str, str] = {
    "bd": "BED",
    "ce": "CES; Current Employment Statistics; establishment survey",
    "ci": "ECI",
    "cm": "ECEC",
    "cu": "CPI; CPI-U",
    "cw": "CPI; CPI-W",
    "cx": "CEX",
    "ei": "MXP",
    "is": "SOII",
    "jt": "JOLTS",
    "la": "LAUS",
    "ln": "household survey",
    "nb": "NCS",
    "nd": "PPI",
    "oe": "OEWS; OES",
    "or": "ORS",
    "pc": "PPI",
    "sm": "SAE",
    "su": "CPI; C-CPI-U; consumer price index",
    "tu": "ATUS",
    "wd": "PPI",
    "wm": "MWE",
    "wp": "PPI",
}


def input_files(program: str) -> tuple[str, ...]:
    """Source file names (relative to the program directory) for one build unit."""
    lookups = LOOKUP_FILES.get(program, ())
    return (f"{program}.series", *(f"{program}.{name}" for name in lookups))


def source_path(program: str, filename: str) -> str:
    """Path of a source file relative to the BLS ``time.series`` root."""
    return f"{program}/{filename}"
