from bls_index.scope import (
    INITIAL_PROGRAMS,
    SURVEY_ALIASES,
    SURVEY_NAMES,
)


def test_every_program_in_scope_has_exactly_one_survey_name():
    assert set(SURVEY_NAMES) == set(INITIAL_PROGRAMS)
    assert all(name.strip() == name and name for name in SURVEY_NAMES.values())


def test_survey_aliases_are_well_formed():
    assert set(SURVEY_ALIASES) <= set(INITIAL_PROGRAMS)
    for program, aliases in SURVEY_ALIASES.items():
        parts = aliases.split("; ")
        assert all(part and part.strip() == part for part in parts), program
        assert len(parts) == len(set(parts)), program
