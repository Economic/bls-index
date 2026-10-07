"""Command-line entry point: ``bls-index``."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from bls_index.clock import SystemClock
from bls_index.events import EventLog
from bls_index.http_source import DEFAULT_BASE_URL, FetchConfig, HttpSource, user_agent_from_env
from bls_index.probe import run_probe
from bls_index.runner_info import runner_info
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

    probe = sub.add_parser("probe", help="inventory real BLS inputs (no object-store writes)")
    probe.add_argument("--programs", type=_programs, default=_programs("initial"),
                       help="comma-separated initial-scope programs, or 'initial' (default)")
    probe.add_argument("--out", type=Path, required=True, help="JSON report path")
    probe.add_argument("--events", type=Path, help="JSON Lines event log path")
    probe.add_argument("--workdir", type=Path, help="temporary download directory")
    probe.add_argument("--base-url", default=DEFAULT_BASE_URL)
    probe.add_argument("--max-concurrency", type=int, default=4)
    probe.add_argument("--parse-check", action="store_true",
                       help="measure polars parse time and peak RSS for each .series")
    probe.add_argument("--keep-files", action="store_true")

    info = sub.add_parser("runner-info", help="print machine resources as JSON")
    info.add_argument("--workdir", type=Path, default=Path("."))

    args = parser.parse_args(argv)
    if args.command == "runner-info":
        print(json.dumps(runner_info(args.workdir), indent=2))
        return 0

    clock = SystemClock()
    events = EventLog(clock)
    config = FetchConfig(
        user_agent=user_agent_from_env(),
        base_url=args.base_url,
        max_concurrency=args.max_concurrency,
    )
    with tempfile.TemporaryDirectory(prefix="bls-index-probe-") as tmp:
        workdir = args.workdir or Path(tmp)
        workdir.mkdir(parents=True, exist_ok=True)
        with HttpSource(config, events, clock) as source:
            report = run_probe(
                args.programs, source, clock, workdir,
                parse_check=args.parse_check, keep_files=args.keep_files,
            )  # fmt: skip
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    if args.events:
        events.write_jsonl(args.events)
    print(json.dumps(report["summary"], indent=2))
    return 0 if not report["summary"]["programs_failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
