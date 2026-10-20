"""Real BLS smoke check. Opt-in only: ``uv run pytest -m live`` with
``BLS_INDEX_USER_AGENT`` set. Never part of default CI."""

from __future__ import annotations

import pytest

from bls_index.builders import build_program
from bls_index.http_source import FetchConfig, HttpSource, user_agent_from_env


@pytest.mark.live
def test_small_real_program_downloads_and_builds(tmp_path):
    with HttpSource(FetchConfig(user_agent=user_agent_from_env())) as source:
        downloads = source.fetch_program("pr", tmp_path)
    frame = build_program("pr", {name: d.path for name, d in downloads.items()})
    assert frame.height > 0
