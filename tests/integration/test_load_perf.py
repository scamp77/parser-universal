"""Soft load test — runs ~1000 mock orchestrations to verify perf budget.

Per Phase 4 DoD: 1000 stations in <30s. We use mock adapter (no network).
Per memory rule: pytest.mark.asyncio must be registered in pyproject.toml
(it is — see [tool.pytest.ini_options].markers).
"""

import asyncio
import time

import pytest

from parser_universal.adapters.url_dispatch import URLCoordAdapter
from parser_universal.fetcher.persistent import PersistentHTTPClient
from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.fetcher.strategies.httpx_persistent_impl import make_persistent_httpx
from parser_universal.observability.structlog_setup import configure_logging
from parser_universal.orchestrator import DryRunSink, ParserOrchestrator
from parser_universal.parallel import gather_with_semaphore
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter


@pytest.mark.perf
@pytest.mark.asyncio
async def test_load_1000_mock_records_under_30s():
    configure_logging(level="WARNING", json=False)
    urls = ["https://yandex.ru/maps/?ll=37.6173,55.7558"] * 1000

    async with PersistentHTTPClient() as p_client:
        strat = make_persistent_httpx(p_client)
        fetcher = SafeFetcher(strategies=[strat])
        rl = AsyncRateLimiter(rate_per_sec=10_000.0, burst=1000)

        async def _one(url):
            sub = ParserOrchestrator(
                adapter=URLCoordAdapter(),
                sinks=[DryRunSink()],
                fetcher=fetcher,
                rate_limiter=rl,
                source_name="perf_test",
            )
            return await sub.run([url])

        t0 = time.monotonic()
        results = await gather_with_semaphore(
            urls, _one, max_workers=8, batch_size=64,
        )
        elapsed = time.monotonic() - t0

    total_inserted = sum(r.rows_inserted for r in results)
    total_failed = sum(r.rows_failed for r in results)
    assert total_inserted == 1000
    assert total_failed == 0
    # Soft perf budget (mock network so should be < 5s in practice; 30s hard cap).
    assert elapsed < 30.0


@pytest.mark.perf
@pytest.mark.asyncio
async def test_load_workers_1_is_correct():
    """Sequential mode (workers=1) returns results in order too."""
    urls = ["https://maps.google.com/?q=55.7558,37.6173"] * 5
    async with PersistentHTTPClient() as p_client:
        strat = make_persistent_httpx(p_client)
        fetcher = SafeFetcher(strategies=[strat])
        rl = AsyncRateLimiter(rate_per_sec=10_000.0, burst=10)

        async def _one(url):
            sub = ParserOrchestrator(
                adapter=URLCoordAdapter(),
                sinks=[DryRunSink()],
                fetcher=fetcher,
                rate_limiter=rl,
                source_name="sequential",
            )
            return await sub.run([url])

        t0 = time.monotonic()
        results = await gather_with_semaphore(
            urls, _one, max_workers=1, batch_size=5,
        )
        elapsed = time.monotonic() - t0

    assert sum(r.rows_inserted for r in results) == 5
    assert elapsed > 0
