"""Unit tests for safe.SafeFetcher (no real network — httpx_mocked)."""

from unittest.mock import AsyncMock, patch

import pytest

from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.types import FetchResult, RetryPolicy


def _ok(status=200, body=b"hello", strategy="mock"):
    return FetchResult(
        url="https://example.test",
        status=status,
        body=body,
        strategy=strategy,
        elapsed_ms=10,
    )


async def _test_first_strategy_wins():
    async def good(url, headers):
        return _ok(strategy="first")

    async def bad(url, headers):
        return _ok(status=500, strategy="second")

    fetcher = SafeFetcher(strategies=[good, bad])
    res = await fetcher.fetch("https://example.test")
    assert res.status == 200
    assert res.strategy == "first"


async def _test_fallback_skips_5xx():
    async def bad(url, headers):
        return _ok(status=500, strategy="first")

    async def good(url, headers):
        return _ok(strategy="second")

    fetcher = SafeFetcher(strategies=[bad, good])
    res = await fetcher.fetch("https://example.test")
    assert res.strategy == "second"


async def _test_retry_when_all_fail():
    # Max retries = 3 → total attempts = 4. First 3 return 500, 4th returns 200.
    call_count = {"n": 0}

    async def eventually_good(url, headers):
        call_count["n"] += 1
        if call_count["n"] < 4:
            return _ok(status=500, strategy=f"try-{call_count['n']}")
        return _ok(strategy="good")

    fetcher = SafeFetcher(
        strategies=[eventually_good],
        retry=RetryPolicy(max_retries=3, initial_backoff_s=0.0),
    )
    res = await fetcher.fetch("https://example.test")
    assert res.status == 200
    assert res.strategy == "good"


async def _test_exhausted_raises():
    async def bad(url, headers):
        return _ok(status=500)

    fetcher = SafeFetcher(
        strategies=[bad],
        retry=RetryPolicy(max_retries=1, initial_backoff_s=0.0),
    )
    with pytest.raises(RuntimeError, match="exhausted"):
        await fetcher.fetch("https://example.test")


async def _test_empty_strategies_rejected():
    with pytest.raises(ValueError):
        SafeFetcher(strategies=[])


# === standalone pytest async wrappers ===
import asyncio


def test_first_strategy_wins():
    asyncio.run(_test_first_strategy_wins())


def test_fallback_skips_5xx():
    asyncio.run(_test_fallback_skips_5xx())


def test_retry_when_all_fail():
    asyncio.run(_test_retry_when_all_fail())


def test_exhausted_raises():
    asyncio.run(_test_exhausted_raises())


def test_empty_strategies_rejected():
    asyncio.run(_test_empty_strategies_rejected())
