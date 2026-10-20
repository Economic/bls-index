"""Command-line entry point: ``bls-index``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bls_index.build import run_build
from bls_index.http_source import DEFAULT_BASE_URL, FetchConfig, HttpSource, user_agent_from_env
from bls_index.scope import INITIAL_PROGRAMS


def _programs(value: str) -> list[str]:
    if value == "initial":
        return list(INITIAL_PROGRAMS)
    programs = [p.strip() for p in value.split(",") if p.strip()]
    unknown = sorted(set(programs) - set(INITIAL_PROGRAMS))
    if unknown or len(set(programs)) != len(programs) or not programs:
        raise argparse.ArgumentTypeError(
            f"expected 'initial' or unique initial-scope programs; unknown: {unknown}"
        )
    return programs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bls-index")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="download BLS files and build the catalog locally")
    build.add_argument("--programs", type=_programs, default=_programs("initial"),
                       help="comma-separated initial-scope programs, or 'initial' (default)")
    build.add_argument("--workdir", type=Path, required=True,
                       help="parent directory for a new, unique run directory")
    build.add_argument("--base-url", default=DEFAULT_BASE_URL)
    build.add_argument("--min-request-interval", type=float, default=1.0,
                       help="minimum seconds between request starts; at least 1 for BLS")
    build.add_argument("--max-attempts", type=int, default=4,
                       help="attempts per file before the program fails")

    args = parser.parse_args(argv)
    try:
        config = FetchConfig(
            user_agent=user_agent_from_env(), base_url=args.base_url,
            min_request_interval=args.min_request_interval, max_attempts=args.max_attempts,
        )  # fmt: skip
    except ValueError as exc:
        parser.error(str(exc))
    with HttpSource(config) as source:
        report = run_build(args.programs, source, args.workdir)
    print(json.dumps({key: report[key] for key in ("status", "run_directory", "catalog", "failure")},
                     indent=2))
    return 0 if report["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
