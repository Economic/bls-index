from bls_index.scope import (
    EXCLUDED_PROGRAMS,
    FUTURE_CHECKPOINT_PROGRAMS,
    INITIAL_PROGRAMS,
    LOOKUP_FILES,
    NATIVE_TITLE_PROGRAMS,
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


def test_future_and_excluded_programs_stay_out():
    assert len(FUTURE_CHECKPOINT_PROGRAMS) == len(set(FUTURE_CHECKPOINT_PROGRAMS)) == 21
    assert len(EXCLUDED_PROGRAMS) == 11
    assert not set(INITIAL_PROGRAMS) & (set(FUTURE_CHECKPOINT_PROGRAMS) | set(EXCLUDED_PROGRAMS))
    assert not set(FUTURE_CHECKPOINT_PROGRAMS) & set(EXCLUDED_PROGRAMS)


def test_lookups_only_for_synthesized_programs():
    assert set(LOOKUP_FILES) == set(SYNTHESIZED_TITLE_PROGRAMS)
    assert input_files("ap") == ("ap.series",)
    assert input_files("pr")[0] == "pr.series"
    assert "pr.measure" in input_files("pr")
