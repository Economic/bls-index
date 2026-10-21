"""Build a small catalog and manifest from the test fixtures, for offline client checks.

Usage: uv run python scripts/fixture_catalog.py OUT_DIR

Writes OUT_DIR/bls_index.parquet (every program's fixture rows, validated like a real
build) and OUT_DIR/latest.json, whose catalog URL is the local file.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from bls_index.builders import build_program
from bls_index.combined_candidate import CATALOG_NAME, write_combined_candidate
from bls_index.scope import INITIAL_PROGRAMS, NATIVE_TITLE_PROGRAMS, input_files

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
ROOTS = {program: FIXTURES / "real_native" for program in NATIVE_TITLE_PROGRAMS} | {
    "pr": FIXTURES / "two_program" / "pr",
    "sm": FIXTURES / "real_synthesized" / "sm",
    "jt": FIXTURES / "real_synthesized" / "jt",
}


def main(out: Path) -> None:
    frames = {
        program: build_program(program, {name: ROOTS[program] / name for name in input_files(program)})
        for program in INITIAL_PROGRAMS
    }
    combined = write_combined_candidate(frames, INITIAL_PROGRAMS, out)
    catalog = (out / CATALOG_NAME).resolve()
    manifest = {
        "manifest_version": 1,
        "schema_version": 1,
        "tag": "fixture",
        "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "catalog": {
            "url": catalog.as_uri(),
            "sha256": hashlib.sha256(catalog.read_bytes()).hexdigest(),
            "bytes": catalog.stat().st_size,
            "rows": combined.height,
        },
    }
    (out / "latest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{combined.height} rows in {catalog}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
