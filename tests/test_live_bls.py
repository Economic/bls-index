"""Real BLS smoke check. Opt-in only: ``uv run pytest -m live`` with
``BLS_INDEX_USER_AGENT`` set. Never part of default CI."""

from __future__ import annotations

import pytest

from bls_index.clock import SystemClock
from bls_index.events import EventLog
from bls_index.http_source import FetchConfig, HttpSource, user_agent_from_env


@pytest.mark.live
def test_small_real_program_downloads_and_rechecks(tmp_path):
    clock = SystemClock()
    config = FetchConfig(user_agent=user_agent_from_env())
    with HttpSource(config, EventLog(clock), clock) as source:
        result = source.fetch_input_set("pr", tmp_path)
    assert result.files[0].bytes > 0
    assert all(r.status == 200 for r in result.files)
