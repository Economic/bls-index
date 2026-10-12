"""The pinned data-dict validator is installed from the lockfile and exposes the
commands the plan relies on."""

from __future__ import annotations

import shutil
import subprocess


def run(*args: str) -> subprocess.CompletedProcess[str]:
    exe = shutil.which("data-dict")
    assert exe, "data-dict not on PATH; run through `uv run`"
    return subprocess.run([exe, *args], capture_output=True, text=True, check=False)


def test_data_dict_version_is_pinned():
    assert run("--version").stdout.strip() == "data-dict 0.0.3"


def test_data_dict_has_validation_commands_with_json():
    for command in ("validate-spec", "validate-meta", "validate-data"):
        result = run(command, "--help")
        assert result.returncode == 0, result.stderr
        assert "--json" in result.stdout
