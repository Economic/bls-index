#!/usr/bin/env bash
# The one build/test command shared by local runs and CI.
# Installs exactly the locked toolchain, then runs the offline test suite
# (no live BLS, no object-store credentials). Extra arguments go to pytest.
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --frozen
uv run --frozen pytest "$@"
