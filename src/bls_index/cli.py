"""Command-line entry point: ``bls-index``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bls_index.clock import SystemClock
from bls_index.events import EventLog
from bls_index.dry_build import run_dry_build, validate_dry_build_base_url
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

    dry = sub.add_parser(
        "dry-build", help="download verified inputs and build local Parquet artifacts only"
    )
    dry.add_argument("--programs", type=_programs, default=_programs("initial"),
                     help="comma-separated initial-scope programs, or 'initial' (default)")
    dry.add_argument("--workdir", type=Path, required=True,
                     help="parent directory for a new, unique dry-build run directory")
    dry.add_argument("--base-url", default=DEFAULT_BASE_URL)
    dry.add_argument("--min-request-interval", type=float, default=1.0,
                     help="minimum seconds between request starts; at least 1 for BLS")
    dry.add_argument("--max-request-attempts", type=int, default=4)
    dry.add_argument("--max-input-set-attempts", type=int, default=3)
    dry.add_argument("--dictionary", type=Path,
                     help="optional authoritative dictionary (defaults to repository root)")

    args = parser.parse_args(argv)
    try:
        validate_dry_build_base_url(args.base_url)
        config = FetchConfig(
            user_agent=user_agent_from_env(), base_url=args.base_url,
            max_concurrency=1, min_request_interval=args.min_request_interval,
            max_request_attempts=args.max_request_attempts,
            max_input_set_attempts=args.max_input_set_attempts,
        )
    except ValueError as exc:
        parser.error(str(exc))
    clock = SystemClock()
    events = EventLog(clock)
    with HttpSource(config, events, clock) as source:
        report = run_dry_build(
            args.programs, source, clock, args.workdir, dictionary_path=args.dictionary,
            events=events,
        )
    print(json.dumps({"status": report["status"], "run_directory": report["run_directory"],
                      "summary": report["summary"]}, indent=2))
    return 1 if report["status"] != "success" else 0


if __name__ == "__main__":
    sys.exit(main())
