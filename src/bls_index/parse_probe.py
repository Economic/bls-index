"""Measure parsing one .series file with polars in a fresh process.

Run as ``python -m bls_index.parse_probe PATH``; prints one JSON object. A separate
process isolates peak RSS from the probe itself. This is a feasibility measurement, not
the Phase 1 parser.
"""

from __future__ import annotations

import json
import resource
import sys
import time

import polars as pl


def main(path: str) -> None:
    started = time.perf_counter()
    result: dict[str, object]
    try:
        frame = pl.read_csv(
            path, separator="\t", has_header=True, infer_schema=False,
            quote_char=None, encoding="utf8-lossy",
        )  # fmt: skip
        result = {"ok": True, "rows": frame.height, "columns": frame.width}
    except Exception as exc:  # report, do not crash the probe
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]}
    result["seconds"] = round(time.perf_counter() - started, 3)
    # ru_maxrss is KiB on Linux.
    result["max_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    result["polars"] = pl.__version__
    print(json.dumps(result))


if __name__ == "__main__":
    main(sys.argv[1])
