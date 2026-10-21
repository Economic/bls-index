from bls_index.scope import (
    INITIAL_PROGRAMS,
    LOOKUP_FILES,
    NATIVE_TITLE_PROGRAMS,
    SURVEY_ALIASES,
    SURVEY_NAMES,
    SYNTHESIZED_TITLE_PROGRAMS,
    input_files,
)

EXPECTED_INITIAL = {
    "ap", "bd", "ce", "ci", "cm", "cu", "cw", "cx", "ei", "ep", "fm", "ip", "is", "jt",
    "kv", "la", "le", "ln", "lu", "mp", "nb", "nd", "oe", "or", "pc", "pr", "sm", "su",
    "tu", "wd", "wm", "wp", "ws",
}  # fmt: skip


def test_initial_scope_is_exactly_the_fixed_33():
    assert len(NATIVE_TITLE_PROGRAMS) == len(set(NATIVE_TITLE_PROGRAMS)) == 30
    assert SYNTHESIZED_TITLE_PROGRAMS == ("sm", "jt", "pr")
    assert set(INITIAL_PROGRAMS) == EXPECTED_INITIAL
    assert len(INITIAL_PROGRAMS) == 33
    assert list(INITIAL_PROGRAMS) == sorted(INITIAL_PROGRAMS)


def test_every_program_in_scope_has_exactly_one_survey_name():
    assert set(SURVEY_NAMES) == set(INITIAL_PROGRAMS)
    assert all(name.strip() == name and name for name in SURVEY_NAMES.values())


def test_survey_aliases_are_well_formed():
    assert set(SURVEY_ALIASES) <= set(INITIAL_PROGRAMS)
    for program, aliases in SURVEY_ALIASES.items():
        parts = aliases.split("; ")
        assert all(part and part.strip() == part for part in parts), program
        assert len(parts) == len(set(parts)), program


def test_lookups_only_for_synthesized_programs():
    assert set(LOOKUP_FILES) == set(SYNTHESIZED_TITLE_PROGRAMS)
    assert input_files("ap") == ("ap.series",)
    assert input_files("pr")[0] == "pr.series"
    assert "pr.measure" in input_files("pr")
