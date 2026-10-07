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
    probe.add_argument("--workdir", type=Path,
                       help="parent directory for the probe's own run directory")
    probe.add_argument("--base-url", default=DEFAULT_BASE_URL)
    probe.add_argument("--max-concurrency", type=int, default=4)
    probe.add_argument("--min-request-interval", type=float, default=1.0,
                       help="minimum seconds between request starts (BLS blocks robots "
                            "requesting multiple times per second; use 0 only for local tests)")
    probe.add_argument("--parse-check", action="store_true",
                       help="measure polars parse time and peak RSS for each .series")
    probe.add_argument("--keep-files", action="store_true",
                       help="keep downloads in a run directory under --workdir (required)")

    info = sub.add_parser("runner-info", help="print machine resources as JSON")
    info.add_argument("--workdir", type=Path, default=Path("."))

    args = parser.parse_args(argv)
    if args.command == "runner-info":
        print(json.dumps(runner_info(args.workdir), indent=2))
        return 0

    if args.keep_files and args.workdir is None:
        parser.error("--keep-files requires --workdir")

    clock = SystemClock()
    events = EventLog(clock)
    config = FetchConfig(
        user_agent=user_agent_from_env(),
        base_url=args.base_url,
        max_concurrency=args.max_concurrency,
        min_request_interval=args.min_request_interval,
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
        args.events.parent.mkdir(parents=True, exist_ok=True)
        events.write_jsonl(args.events)
    summary = report["summary"]
    print(json.dumps(summary, indent=2))
    return 1 if summary["programs_failed"] or summary["parse_check_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
