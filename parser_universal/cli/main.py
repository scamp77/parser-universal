"""parser-cli — Phase 2: orchestrate OR single-adapter mode.

Usage:
    parser-cli run --adapter gpx --locator tests/data/sample.gpx
    parser-cli orchestrate --adapter url --locators urls.txt --sink dryrun
    parser-cli validate-config <yaml-path>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from parser_universal import __version__
from parser_universal.adapters import (
    APIAdapter,
    GPXAdapter,
    HTMLAdapter,
    URLCoordAdapter,
)
from parser_universal.cli.orchestrate_cmd import cmd_orchestrate
from parser_universal.cli.run_cmd import cmd_run
from parser_universal.cli.run_config_cmd import cmd_run_config
from parser_universal.cli.validate_cmd import cmd_validate_config
from parser_universal.cli.shared import ADAPTERS, ENRICHERS

__all__ = ["cli", "ADAPTERS"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="parser-cli")
    p.add_argument("--version", action="version", version=f"parser-universal {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="Run an adapter against a single locator (no sink)")
    pr.add_argument("--adapter", required=True, choices=sorted(ADAPTERS.keys()))
    pr.add_argument("--locator", required=True)
    pr.set_defaults(func=cmd_run)

    po = sub.add_parser(
        "orchestrate",
        help="Run the full orchestrator: fetch + (optional) normalize + sink + FailureSink + DailySourceLog",
    )
    po.add_argument("--adapter", required=True, choices=sorted(ADAPTERS.keys()))
    po.add_argument(
        "--locators",
        required=True,
        help="Newline-separated file path of locators, OR a comma-separated inline list",
    )
    po.add_argument(
        "--sink",
        choices=("dryrun", "postgres"),
        default="dryrun",
        help="Persist target. postgres requires POSTGRES_DSN env.",
    )
    po.add_argument(
        "--table",
        default="entities",
        help="Postgres table (only when --sink=postgres)",
    )
    po.add_argument(
        "--source-name",
        default=None,
        help="Override source name for daily_source_log. Defaults to adapter source.",
    )
    po.add_argument(
        "--failure-sink",
        action="store_true",
        help="Write failures to raw_routes_failed (only when --sink=postgres)",
    )
    po.add_argument(
        "--enricher",
        action="append",
        choices=sorted(ENRICHERS.keys()),
        help="Enricher to apply (Phase 3). Repeatable. Available: brouter.",
    )
    po.set_defaults(func=cmd_orchestrate)

    pv = sub.add_parser("validate-config", help="Validate a YAML config file")
    pv.add_argument("path")
    pv.set_defaults(func=cmd_validate_config)

    prc = sub.add_parser(
        "run-config",
        help="Run a parser pipeline from a YAML config file (Phase 4)",
    )
    prc.add_argument("config", help="Path to YAML config file")
    prc.set_defaults(func=cmd_run_config)
    return p


def cli() -> None:
    parser = build_parser()
    args = parser.parse_args()
    rc = args.func(args)
    sys.exit(rc)


if __name__ == "__main__":
    cli()
