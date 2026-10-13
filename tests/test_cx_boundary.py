from pathlib import Path

from bls_index.native_builders import parse_native_series


FIXTURE = Path(__file__).parent / "fixtures" / "native" / "cx-boundary.series"


def test_real_cx_minimum_and_maximum_series_id_lengths_match_components():
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # Exact header and two source rows from the verified download.
    ids = [line.split("\t", 1)[0].strip() for line in lines[1:]]
    assert ids == ["CXUHAMLB0101M", "CXUBEERNALELB0101M"]
    assert [len(series_id) for series_id in ids] == [13, 18]

    frame = parse_native_series(FIXTURE, "cx")
    assert frame.height == 2
    assert frame.get_column("series_id").to_list() == ids
