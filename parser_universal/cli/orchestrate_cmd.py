"""`parser-cli orchestrate` — full Phase 2/3 run with sink, enricher, observability."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from parser_universal.cli.shared import ADAPTERS, ENRICHERS
from parser_universal.observability.daily_source_log import DailySourceLog
from parser_universal.observability.structlog_setup import configure_logging
from parser_universal.orchestrator import DryRunSink, ParserOrchestrator
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter
from parser_universal.sinks.failure import FailureSink


def _load_locators(arg):
    p = Path(arg)
    if p.is_file():
        return [line.strip() for line in p.read_text().splitlines() if line.strip()]
    if "," in arg:
        parts = re.split(r",\s*(?=https?://)", arg)
        return [x.strip() for x in parts if x.strip()]
    return [arg]


def _build_sink(args):
    if args.sink == "dryrun":
        return DryRunSink()
    from parser_universal.db import get_conn
    from parser_universal.sinks.postgres import PostgresSink

    conn = get_conn()
    return PostgresSink(conn, table=args.table, soft_delete_col="removed_at")


def _build_failure_sink_if_requested(args):
    if not args.failure_sink:
        return None
    from parser_universal.db import get_conn

    return FailureSink(get_conn())


def _build_daily_log(args):
    if args.sink != "postgres":
        return None
    from parser_universal.db import get_conn

    return DailySourceLog(get_conn())


def _build_enrichers(args):
    out = []
    for name in args.enricher or []:
        cls = ENRICHERS.get(name)
        if cls is None:
            print(f"unknown enricher: {name}", file=sys.stderr)
            sys.exit(2)
        out.append(cls())
    return out


async def _run_orchestrate(args):
    configure_logging(level="INFO", json=True)
    if args.adapter not in ADAPTERS:
        print(f"unknown adapter: {args.adapter}", file=sys.stderr)
        return 2
    adapter = ADAPTERS[args.adapter]()
    sink = _build_sink(args)
    failure_sink = _build_failure_sink_if_requested(args)
    daily_log = _build_daily_log(args)
    enrichers = _build_enrichers(args)

    orch = ParserOrchestrator(
        adapter=adapter,
        normalizer=None,
        sinks=[sink] if sink else [DryRunSink()],
        failure_sink=failure_sink,
        daily_log=daily_log,
        enrichers=enrichers,
        fetcher=adapter.source_safe_fetcher(),
        rate_limiter=AsyncRateLimiter(rate_per_sec=2.0, burst=4),
        source_name=args.source_name or adapter.source,
    )

    locs = _load_locators(args.locators)
    if not locs:
        print("no locators provided", file=sys.stderr)
        return 1

    res = await orch.run(locs)
    out = {
        "source": orch.source_name,
        "sink": args.sink,
        "enrichers": [e.name for e in enrichers],
        "locators": len(locs),
        "rows_total": res.rows_total,
        "rows_inserted": res.rows_inserted,
        "rows_updated": res.rows_updated,
        "rows_skipped": res.rows_skipped,
        "rows_failed": res.rows_failed,
        "duration_ms": res.duration_ms,
        "errors_sample": res.errors[:3],
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if res.rows_failed == 0 else 1


def cmd_orchestrate(args):
    return asyncio.run(_run_orchestrate(args))
