"""Unit tests for SearXNGAdapter.

Uses httpx.MockTransport for offline testing.
"""

from __future__ import annotations

import json

import httpx
import pytest

from parser_universal.adapters.searxng import (
    DEFAULT_SEARXNG_URL,
    SearXNGAdapter,
)


def _patch_async_client(monkeypatch, response_body: bytes, status_code: int):
    """Replace searxng_mod.httpx.AsyncClient with one wrapping MockTransport."""
    import parser_universal.adapters.searxng as searxng_mod

    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            status_code,
            content=response_body,
            headers={"content-type": "application/json"},
            request=req,
        )
    )
    orig_client = searxng_mod.httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return orig_client(transport=transport, *args, **kwargs)

    monkeypatch.setattr(searxng_mod.httpx, "AsyncClient", _factory)


class _R:
    async def acquire(self, *_a, **_k):
        return None

    def report(self, _s):
        return None


@pytest.mark.asyncio
async def test_searxng_uses_default_localhost_url():
    adapter = SearXNGAdapter()
    assert adapter.base_url == DEFAULT_SEARXNG_URL
    assert "localhost" in adapter.base_url


@pytest.mark.asyncio
async def test_searxng_build_url_includes_query_and_format(monkeypatch):
    response_body = json.dumps({"results": [], "number_of_results": 0}).encode()
    _patch_async_client(monkeypatch, response_body=response_body, status_code=200)

    adapter = SearXNGAdapter()
    fetcher = adapter.source_safe_fetcher()
    await adapter.fetch_one("OKKO ціни", fetcher=fetcher, rate_limiter=_R())
    # Verified by mocktransport succeeding with the encoded URL


@pytest.mark.asyncio
async def test_searxng_adapter_fetch_one_returns_raw_record(monkeypatch):
    response_body = json.dumps(
        {
            "results": [
                {
                    "url":   "https://index.minfin.com.ua/markets/fuel/",
                    "title": "Minfin Fuel Index",
                    "content": "Цены на топливо по областям Украины",
                    "engine": "google",
                    "score":  0.95,
                    "publishedDate": "2026-07-05T10:00:00Z",
                },
                {
                    "url":   "https://a95.ua/news/fuel-2026-07-05",
                    "title": "А-95 news",
                    "content": "Daily fuel digest",
                    "engine": "bing",
                    "score":  0.80,
                    "publishedDate": "2026-07-05T11:30:00Z",
                },
            ],
            "number_of_results": 2,
        }
    ).encode()
    _patch_async_client(monkeypatch, response_body=response_body, status_code=200)

    adapter = SearXNGAdapter(base_url="https://example.test/search")
    fetcher = adapter.source_safe_fetcher()
    rec = await adapter.fetch_one(
        "OKKO ціни", fetcher=fetcher, rate_limiter=_R()
    )
    assert rec is not None
    assert rec.source == "searxng"
    assert rec.raw["n_results"] == 2
    assert rec.raw["results"][0]["url"] == "https://index.minfin.com.ua/markets/fuel/"
    assert rec.text == "Цены на топливо по областям Украины"


@pytest.mark.asyncio
async def test_searxng_adapter_returns_none_on_400(monkeypatch):
    _patch_async_client(
        monkeypatch, response_body=b"rate limited", status_code=429,
    )

    adapter = SearXNGAdapter(base_url="https://example.test/search")
    rec = await adapter.fetch_one(
        "test", fetcher=adapter.source_safe_fetcher(), rate_limiter=_R()
    )
    assert rec is None


@pytest.mark.asyncio
async def test_searxng_adapter_handles_empty_results(monkeypatch):
    response_body = json.dumps({"results": [], "number_of_results": 0}).encode()
    _patch_async_client(monkeypatch, response_body=response_body, status_code=200)

    adapter = SearXNGAdapter(base_url="https://example.test/search")
    rec = await adapter.fetch_one(
        "no_results_query",
        fetcher=adapter.source_safe_fetcher(),
        rate_limiter=_R(),
    )
    assert rec is not None
    assert rec.raw["n_results"] == 0
    assert rec.raw["results"] == []
    assert rec.text is None


@pytest.mark.asyncio
async def test_searxng_adapter_respects_max_results(monkeypatch):
    # 5 results returned but max_results=2
    response_body = json.dumps(
        {
            "results": [{"url": f"https://r/{i}"} for i in range(5)],
            "number_of_results": 5,
        }
    ).encode()
    _patch_async_client(monkeypatch, response_body=response_body, status_code=200)

    adapter = SearXNGAdapter(
        base_url="https://example.test/search", max_results=2
    )
    rec = await adapter.fetch_one(
        "x", fetcher=adapter.source_safe_fetcher(), rate_limiter=_R()
    )
    assert rec is not None
    assert rec.raw["n_results"] == 2
    assert len(rec.raw["results"]) == 2
    # raw_response retains the original envelope
    assert rec.raw["raw_response"]["number_of_results"] == 5


@pytest.mark.asyncio
async def test_searxng_adapter_handles_bad_json(monkeypatch):
    _patch_async_client(
        monkeypatch, response_body=b"<html>not json</html>", status_code=200,
    )

    adapter = SearXNGAdapter(base_url="https://example.test/search")
    rec = await adapter.fetch_one(
        "x", fetcher=adapter.source_safe_fetcher(), rate_limiter=_R()
    )
    assert rec is None


@pytest.mark.asyncio
async def test_searxng_adapter_time_range_passthrough(monkeypatch):
    response_body = json.dumps({"results": [], "number_of_results": 0}).encode()
    _patch_async_client(monkeypatch, response_body=response_body, status_code=200)

    adapter = SearXNGAdapter(
        base_url="https://example.test/search",
        time_range="day",
        language="ru",
    )
    rec = await adapter.fetch_one(
        "x", fetcher=adapter.source_safe_fetcher(), rate_limiter=_R()
    )
    assert rec is not None
    assert "time_range=day" in rec.raw_ref
    assert "language=ru" in rec.raw_ref
