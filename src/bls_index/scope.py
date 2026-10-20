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


def input_files(program: str) -> tuple[str, ...]:
    """Source file names (relative to the program directory) for one build unit."""
    lookups = LOOKUP_FILES.get(program, ())
    return (f"{program}.series", *(f"{program}.{name}" for name in lookups))


def source_path(program: str, filename: str) -> str:
    """Path of a source file relative to the BLS ``time.series`` root."""
    return f"{program}/{filename}"
