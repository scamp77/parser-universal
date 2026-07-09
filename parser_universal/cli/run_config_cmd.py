"""`parser-cli run-config` — orchestrator driven by a YAML config file.

Usage:
    parser-cli run-config configs/minfin_smoke.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from parser_universal.cli.shared import ADAPTERS, ENRICHERS
from parser_universal.config_loader import load_config, validate_config
from parser_universal.fetcher.persistent import PersistentHTTPClient
from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.fetcher.strategies import httpx_strategy, jina_fallback
from parser_universal.fetcher.strategies.httpx_persistent_impl import make_persistent_httpx
from parser_universal.observability.daily_source_log import DailySourceLog
from parser_universal.observability.structlog_setup import configure_logging
from parser_universal.orchestrator import DryRunSink, ParserOrchestrator
from parser_universal.parallel import gather_with_semaphore
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter
from parser_universal.sinks.failure import FailureSink


def _build_sink(cfg):
    if cfg.sink.type == "dryrun":
        return DryRunSink()
    from parser_universal.db import get_conn
    from parser_universal.sinks.postgres import PostgresSink

    conn = get_conn()
    return PostgresSink(conn, table=cfg.sink.table, soft_delete_col="removed_at")


def _build_failure_sink(cfg):
    if not cfg.failure_sink:
        return None
    from parser_universal.db import get_conn

    return FailureSink(get_conn())


def _build_daily_log(cfg):
    if not cfg.daily_log or cfg.sink.type != "postgres":
        return None
    from parser_universal.db import get_conn

    return DailySourceLog(get_conn())


def _build_enrichers(cfg):
    out = []
    for name in cfg.enrichers:
        cls = ENRICHERS.get(name)
        if cls is None:
            print(f"unknown enricher: {name}", file=sys.stderr)
            sys.exit(2)
        out.append(cls())
    return out


def _build_fetcher(cfg):
    """Build a SafeFetcher honoring `fetcher.persistent` flag."""
    if cfg.fetcher.persistent:
        client = PersistentHTTPClient()
        persistent_strat = make_persistent_httpx(client)
        strategies = [persistent_strat]
        # Optional fallback chain via jina if user requested.
        if "jina_fallback" in cfg.fetcher.strategies:
            strategies.append(jina_fallback)
        return SafeFetcher(strategies=strategies), client
    # Non-persistent: one-shot httpx + jina fallback.
    strats = []
    if "httpx" in cfg.fetcher.strategies:
        strats.append(httpx_strategy)
    if "jina_fallback" in cfg.fetcher.strategies:
        strats.append(jina_fallback)
    return SafeFetcher(strategies=strats), None


async def _run_config(args):
    configure_logging(level="INFO", json=True)
    raw = load_config(args.config)
    cfg = validate_config(raw)
    if cfg.adapter not in ADAPTERS:
        print(f"unknown adapter: {cfg.adapter}", file=sys.stderr)
        return 2
    adapter = ADAPTERS[cfg.adapter]()
    fetcher, persistent_client = _build_fetcher(cfg)
    sink = _build_sink(cfg)
    failure_sink = _build_failure_sink(cfg)
    daily_log = _build_daily_log(cfg)
    enrichers = _build_enrichers(cfg)

    orch = ParserOrchestrator(
        adapter=adapter,
        normalizer=None,
        sinks=[sink] if sink else [DryRunSink()],
        failure_sink=failure_sink,
        daily_log=daily_log,
        enrichers=enrichers,
        fetcher=fetcher,
        rate_limiter=AsyncRateLimiter(
            rate_per_sec=cfg.rate_limiter.rate_per_sec,
            burst=cfg.rate_limiter.burst,
        ),
        source_name=cfg.source_name or adapter.source,
    )

    locs = cfg.all_locators()
    if not locs:
        print("config has no locator(s) — set `locator` or `locators`", file=sys.stderr)
        return 1

    # Optional parallel mode (workers > 1) — Phase 4.
    if cfg.parallel.workers > 1:
        async def _one(loc):
            sub = ParserOrchestrator(
                adapter=ADAPTERS[cfg.adapter](),
                sinks=orch.sinks,
                failure_sink=orch.failure_sink,
                daily_log=orch.daily_log,
                enrichers=orch.enrichers,
                fetcher=fetcher,
                rate_limiter=orch.rate_limiter,
                source_name=orch.source_name,
            )
            return await sub.run([loc])

        try:
            results = await gather_with_semaphore(
                locs,
                _one,
                max_workers=cfg.parallel.workers,
                batch_size=cfg.parallel.batch_size,
            )
            merged = {
                "rows_total": sum(r.rows_total for r in results),
                "rows_inserted": sum(r.rows_inserted for r in results),
                "rows_updated": sum(r.rows_updated for r in results),
                "rows_skipped": sum(r.rows_skipped for r in results),
                "rows_failed": sum(r.rows_failed for r in results),
                "duration_ms": sum(r.duration_ms for r in results),
            }
            out = {
                "mode": "parallel",
                "workers": cfg.parallel.workers,
                "batch_size": cfg.parallel.batch_size,
                "locators": len(locs),
                **merged,
            }
        finally:
            if persistent_client:
                await persistent_client.aclose()
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0 if merged["rows_failed"] == 0 else 1

    # Sequential path.
    try:
        res = await orch.run(locs)
    finally:
        if persistent_client:
            await persistent_client.aclose()
    out = {
        "mode": "sequential",
        "source": orch.source_name,
        "sink": cfg.sink.type,
        "enrichers": [e.name for e in enrichers],
        "locators": len(locs),
        "rows_total": res.rows_total,
        "rows_inserted": res.rows_inserted,
        "rows_updated": res.rows_updated,
        "rows_skipped": res.rows_skipped,
        "rows_failed": res.rows_failed,
        "duration_ms": res.duration_ms,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if res.rows_failed == 0 else 1


def cmd_run_config(args):
    return asyncio.run(_run_config(args))
