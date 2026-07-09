"""Unit tests for orchestrator with enrichers (Phase 3).

Smoke-tests the full Layer 1 → 2 → 3 → 4 chain via a no-op enricher
that just bumps a counter (validates that orchestrator does invoke the
enricher per row).
"""

from __future__ import annotations

import asyncio

from parser_universal.adapters.url_dispatch import URLCoordAdapter
from parser_universal.enrichers.base import Enricher, EnrichmentContext
from parser_universal.observability.structlog_setup import configure_logging
from parser_universal.orchestrator import DryRunSink, ParserOrchestrator
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter
from parser_universal.types import DomainEntity


class BumpAttrsEnricher:
    """Test enricher: appends a stamp to entity.attrs['bumped']."""

    name = "bump"

    def __init__(self):
        self.calls = 0

    async def enrich(self, entity, ctx):
        self.calls += 1
        from dataclasses import replace
        attrs = dict(entity.attrs)
        attrs["bumped"] = attrs.get("bumped", 0) + 1
        return replace(entity, attrs=attrs)


def test_orchestrator_invokes_enricher_for_each_row():
    configure_logging(level="WARNING", json=False)
    enricher = BumpAttrsEnricher()
    dryrun = DryRunSink()
    orch = ParserOrchestrator(
        adapter=URLCoordAdapter(),
        enrichers=[enricher],
        sinks=[dryrun],
        rate_limiter=AsyncRateLimiter(rate_per_sec=100.0, burst=10),
        source_name="url_with_enricher",
    )
    res = asyncio.run(
        orch.run([
            "https://yandex.ru/maps/?ll=37.6173,55.7558",
            "https://maps.google.com/?q=55.7558,37.6173",
            "https://example.com/skip",
        ])
    )
    # Enricher ran on 2 successfully-fetched rows (1 was skipped).
    assert enricher.calls == 2
    assert res.rows_inserted == 2
    assert res.rows_skipped == 1
    for record in dryrun.records:
        assert record.attrs.get("bumped") == 1


def test_orchestrator_enricher_failure_does_not_abort_row():
    """If enricher raises, orchestrator logs and continues."""
    configure_logging(level="WARNING", json=False)

    class BoomEnricher:
        name = "boom"

        async def enrich(self, entity, ctx):
            raise RuntimeError("enrich exploded")

    dryrun = DryRunSink()
    orch = ParserOrchestrator(
        adapter=URLCoordAdapter(),
        enrichers=[BoomEnricher()],
        sinks=[dryrun],
        rate_limiter=AsyncRateLimiter(rate_per_sec=100.0, burst=10),
        source_name="boom",
    )
    res = asyncio.run(
        orch.run(["https://yandex.ru/maps/?ll=37.6173,55.7558"])
    )
    assert res.rows_inserted == 1  # still persisted
    assert res.rows_failed == 0    # enrich-failure is NOT a row failure


def test_orchestrator_no_enrichers_attribute_does_not_crash():
    """If enrichers= omitted, attribute is empty list."""
    configure_logging(level="WARNING", json=False)
    dryrun = DryRunSink()
    orch = ParserOrchestrator(
        adapter=URLCoordAdapter(),
        sinks=[dryrun],
        rate_limiter=AsyncRateLimiter(rate_per_sec=100.0, burst=10),
    )
    assert orch.enrichers == []
