"""Unit tests for URL dispatch adapter (no network — pure URL parsing)."""

import asyncio

from parser_universal.adapters.url_dispatch import URLCoordAdapter


def test_yandex_url_returns_raw_record():
    adapter = URLCoordAdapter()
    fetcher = adapter.source_safe_fetcher()

    class _NoOpRL:
        async def acquire(self, *_a, **_k):
            return None

        def report(self, _status):
            return None

    url = "https://yandex.ru/maps/?ll=37.6173,55.7558"

    async def run():
        return await adapter.fetch_one(url, fetcher=fetcher, rate_limiter=_NoOpRL())

    rec = asyncio.run(run())
    assert rec is not None
    assert rec.source == "url"
    assert rec.coord_hint == (55.7558, 37.6173)


def test_unknown_url_returns_none():
    adapter = URLCoordAdapter()
    fetcher = adapter.source_safe_fetcher()

    class _NoOpRL:
        async def acquire(self, *_a, **_k):
            return None

        def report(self, _status):
            return None

    async def run():
        return await adapter.fetch_one("https://example.com/foo", fetcher=fetcher, rate_limiter=_NoOpRL())

    assert asyncio.run(run()) is None
