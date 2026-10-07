"""Fixed program scope for the first publication.

The initial published scope is fixed here and in tests. It is never inferred from the
BLS directory listing or from future checkpoint lists. After first publication, the
daily scope comes from the published manifest's ``required_programs``.
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

# Lookup files needed to synthesize titles. Provisional: taken from the BLS directory
# listings and .series headers on 2026-10-07 (dimension and seasonal lookups only;
# footnotes are not part of titles). Phase 1 title templates confirm or trim this list,
# and the source probe verifies each file is retrievable.
LOOKUP_FILES: dict[str, tuple[str, ...]] = {
    "sm": ("state", "area", "supersector", "industry", "data_type", "seasonal"),
    "jt": ("industry", "state", "area", "sizeclass", "dataelement", "ratelevel", "seasonal"),
    "pr": ("sector", "class", "measure", "duration", "seasonal"),
}

# Not v1 scope. Listed only so tests can assert they never leak into the initial list.
FUTURE_CHECKPOINT_PROGRAMS: tuple[str, ...] = (
    # Checkpoint 3: frozen twins.
    "ee", "sa", "mu", "mw", "pd", "cc", "ec", "nc", "eb", "jl",
    # Checkpoint 4: injuries.
    "ii", "sh", "hs", "si",
    # Checkpoint 5: standalone frozen.
    "ml", "gp", "in", "gg", "bp", "li", "bg",
)  # fmt: skip
EXCLUDED_PROGRAMS: tuple[str, ...] = (
    "nw", "ca", "cb", "cd", "cf", "ch", "cs", "fa", "fi", "fw", "hc",
)  # fmt: skip


def input_files(program: str) -> tuple[str, ...]:
    """Source file names (relative to the program directory) for one build unit."""
    lookups = LOOKUP_FILES.get(program, ())
    return (f"{program}.series", *(f"{program}.{name}" for name in lookups))


def source_path(program: str, filename: str) -> str:
    """Path of a source file relative to the BLS ``time.series`` root."""
    return f"{program}/{filename}"
