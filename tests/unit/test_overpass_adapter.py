"""Unit tests for OverpassAdapter.

Uses httpx.MockTransport for offline testing. We monkeypatch
`overpass_mod.httpx.AsyncClient` to forward to a MockTransport carrying
the desired response.

(benz durable rule: maps.mail.ru mirror; nwr not node; out center;)
"""

from __future__ import annotations

import json

import httpx
import pytest

from parser_universal.adapters.overpass import (
    DEFAULT_OVERPASS_URL,
    OverpassAdapter,
)


def _patch_async_client(monkeypatch, response_body: bytes, status_code: int):
    """Replace overpass_mod.httpx.AsyncClient with one wrapping MockTransport."""
    import parser_universal.adapters.overpass as overpass_mod

    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            status_code,
            content=response_body,
            headers={"content-type": "application/json"},
            request=req,
        )
    )
    orig_client = overpass_mod.httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return orig_client(transport=transport, *args, **kwargs)

    monkeypatch.setattr(overpass_mod.httpx, "AsyncClient", _factory)


class _R:
    async def acquire(self, *_a, **_k):
        return None

    def report(self, _s):
        return None


@pytest.mark.asyncio
async def test_overpass_uses_default_mirror_url():
    adapter = OverpassAdapter()
    assert adapter.base_url == DEFAULT_OVERPASS_URL
    assert "mail.ru" in adapter.base_url  # durable rule mirror


@pytest.mark.asyncio
async def test_overpass_adapter_uses_real_overpass_url_by_default():
    adapter = OverpassAdapter()
    assert "overpass-api.de" not in adapter.base_url


@pytest.mark.asyncio
async def test_overpass_adapter_fetch_one_returns_raw_record(monkeypatch):
    response_body = json.dumps(
        {
            "elements": [
                {
                    "type": "way",
                    "id": 12345,
                    "center": {"lat": 50.5, "lon": 30.5},
                    "tags": {"amenity": "fuel", "brand": "OKKO"},
                },
                {
                    "type": "node",
                    "id": 67890,
                    "lat": 49.8,
                    "lon": 24.0,
                    "tags": {"amenity": "fuel", "brand": "WOG"},
                },
            ]
        }
    ).encode()
    _patch_async_client(monkeypatch, response_body=response_body, status_code=200)

    adapter = OverpassAdapter(base_url="https://example.test/overpass")
    fetcher = adapter.source_safe_fetcher()
    rec = await adapter.fetch_one(
        '[out:json];nwr["amenity"="fuel"](50.0,30.0,51.0,31.0);out center;',
        fetcher=fetcher,
        rate_limiter=_R(),
    )
    assert rec is not None
    assert rec.source == "overpass"
    assert rec.coord_hint == (50.5, 30.5)
    assert rec.raw["n_elements"] == 2
    assert rec.raw["elements"][0]["center"] == {"lat": 50.5, "lon": 30.5}
    assert rec.raw["elements"][1]["lat"] == 49.8


@pytest.mark.asyncio
async def test_overpass_adapter_returns_none_on_400(monkeypatch):
    _patch_async_client(
        monkeypatch, response_body=b"rate limited", status_code=429,
    )

    adapter = OverpassAdapter(base_url="https://example.test/overpass")
    rec = await adapter.fetch_one(
        "nwr",
        fetcher=adapter.source_safe_fetcher(),
        rate_limiter=_R(),
    )
    assert rec is None


@pytest.mark.asyncio
async def test_overpass_adapter_handles_empty_elements(monkeypatch):
    response_body = json.dumps({"elements": []}).encode()
    _patch_async_client(monkeypatch, response_body=response_body, status_code=200)

    adapter = OverpassAdapter(base_url="https://example.test/overpass")
    rec = await adapter.fetch_one(
        "nwr-with-no-matches",
        fetcher=adapter.source_safe_fetcher(),
        rate_limiter=_R(),
    )
    assert rec is not None
    assert rec.raw["elements"] == []
    assert rec.coord_hint is None  # no elements → no first-coord
