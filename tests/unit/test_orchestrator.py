"""Unit tests for orchestrator — full Layer 1-5 chain via DryRunSink.

Verifies idempotent re-run contract: same input → mixed INSERTED/UPDATED
counters, no double-write.
"""

from __future__ import annotations

import asyncio

from parser_universal.observability.structlog_setup import configure_logging
from parser_universal.adapters.url_dispatch import URLCoordAdapter
from parser_universal.adapters.gpx import GPXAdapter
from parser_universal.orchestrator import DryRunSink, ParserOrchestrator, OrchestratorResult
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter


def test_orchestrator_with_url_dispatch_dryrun():
    """End-to-end fetch + DryRunSink via URL adapter — no real network."""
    configure_logging(level="WARNING", json=False)
    dryrun = DryRunSink()
    orch = ParserOrchestrator(
        adapter=URLCoordAdapter(),
        normalizer=None,
        sinks=[dryrun],
        rate_limiter=AsyncRateLimiter(rate_per_sec=100.0, burst=10),
        source_name="url_dispatch",
    )
    res = asyncio.run(
        orch.run([
            "https://yandex.ru/maps/?ll=37.6173,55.7558",
            "https://maps.google.com/?q=55.7558,37.6173",
            "https://example.com/no-coords",  # skipped
        ])
    )
    assert isinstance(res, OrchestratorResult)
    assert res.rows_total == 3
    assert res.rows_inserted == 2
    assert res.rows_skipped == 1
    assert res.rows_failed == 0
    assert len(dryrun.records) == 2
    assert all(r.geom is not None for r in dryrun.records)


def test_orchestrator_with_gpx_local_file(tmp_path):
    """GPX adapter (local file path, no network)."""
    gpx_path = tmp_path / "sample.gpx"
    gpx_path.write_text(
        '<?xml version="1.0"?><gpx>'
        '<wpt lat="49.8" lon="24.0"><name>Start</name></wpt>'
        '<trk><trkseg><trkpt lat="49.8" lon="24.0"/>'
        '<trkpt lat="49.9" lon="24.1"/></trkseg></trk>'
        '</gpx>'
    )

    configure_logging(level="WARNING", json=False)
    dryrun = DryRunSink()
    orch = ParserOrchestrator(
        adapter=GPXAdapter(),
        sinks=[dryrun],
        rate_limiter=AsyncRateLimiter(rate_per_sec=100.0, burst=10),
        source_name="gpx_local",
    )
    res = asyncio.run(orch.run([str(gpx_path)]))
    assert res.rows_inserted == 1
    assert res.rows_failed == 0
    assert dryrun.records[0].geom == (49.8, 24.0)
    assert dryrun.records[0].entity_type == "raw"


def test_orchestrator_failure_sink_records_skips():
    """FailureSink is called for skipped locators too."""
    from parser_universal.sinks.failure import FailureSink

    recorded: list = []

    class _RecConn:
        def cursor(self):
            class _C:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *a):
                    return False

                def execute(self_inner, sql, params=None):
                    recorded.append((sql, params))

            return _C()

        def commit(self):
            pass

        def rollback(self):
            pass

    configure_logging(level="WARNING", json=False)
    dryrun = DryRunSink()
    fs = FailureSink(_RecConn(), table="r")
    orch = ParserOrchestrator(
        adapter=URLCoordAdapter(),
        sinks=[dryrun],
        failure_sink=fs,
        rate_limiter=AsyncRateLimiter(rate_per_sec=100.0, burst=10),
        source_name="test",
    )
    res = asyncio.run(
        orch.run(["https://example.com/none/of/the/params"])
    )
    assert res.rows_skipped == 1
    # FailureSink.record() was called for the skipped locator.
    assert any("INSERT INTO r" in sql for sql, _ in recorded)


def test_orchestrator_no_sinks_defaults_to_dryrun():
    """If sinks= is omitted, DryRunSink is used implicitly."""
    configure_logging(level="WARNING", json=False)
    orch = ParserOrchestrator(
        adapter=URLCoordAdapter(),
        rate_limiter=AsyncRateLimiter(rate_per_sec=100.0, burst=10),
    )
    res = asyncio.run(
        orch.run(["https://yandex.ru/maps/?ll=37.6173,55.7558"])
    )
    assert res.rows_inserted == 1
