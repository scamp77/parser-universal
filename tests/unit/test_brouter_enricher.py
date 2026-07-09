"""Unit tests for BrouterEnricher — no real network. Mock fetcher is used.

We verify:
  - URL construction (lonlats, profile=river, alternativeidx=0, format=geojson)
  - GeoJSON LineString → coords stamped on entity.attrs
  - Track quality thresholding
  - Failure modes (400, empty features, non-LineString) → silent no-op
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from parser_universal.enrichers.base import EnrichmentContext
from parser_universal.enrichers.brouter import BrouterEnricher
from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.fetcher.strategies.httpx_impl import httpx_strategy
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter
from parser_universal.types import DomainEntity, RawRecord


class _MockFetcher:
    """Record fetch() calls and return a programmable FetchResult."""

    def __init__(self, status=200, body=b"", strategy="mock"):
        self.calls: list[str] = []
        self._status = status
        self._body = body
        self._strategy = strategy

    async def fetch(self, url: str, headers=None):
        from parser_universal.types import FetchResult
        self.calls.append(url)
        return FetchResult(
            url=url,
            status=self._status,
            body=self._body,
            strategy=self._strategy,
        )


class _NoOpRL:
    def __init__(self):
        self.reported: list[int] = []

    async def acquire(self, *_a, **_k):
        return None

    def report(self, status):
        self.reported.append(status)


def _entity(*, attrs=None):
    return DomainEntity(
        entity_type="route",
        source="sup-app",
        source_id="r-1",
        geom=(50.5, 30.5),  # (lat, lon)
        attrs={
            "finish_lat": 50.6,
            "finish_lon": 30.6,
            **(attrs or {}),
        },
    )


def _ctx(*, status=200, body=b""):
    fetcher = _MockFetcher(status=status, body=body)
    rl = _NoOpRL()
    return fetcher, rl


@pytest.mark.asyncio
async def test_brouter_enricher_skips_when_no_finish():
    enricher = BrouterEnricher()
    f, rl = _ctx()
    e = DomainEntity(
        entity_type="route", source="x", source_id="y", geom=(50.5, 30.5), attrs={}
    )
    out = await enricher.enrich(e, EnrichmentContext(fetcher=f, rate_limiter=rl))
    assert out is e
    assert f.calls == []


@pytest.mark.asyncio
async def test_brouter_enricher_skips_when_no_geom():
    enricher = BrouterEnricher()
    f, rl = _ctx()
    e = DomainEntity(
        entity_type="route", source="x", source_id="y", geom=None, attrs={}
    )
    out = await enricher.enrich(e, EnrichmentContext(fetcher=f, rate_limiter=rl))
    assert out is e
    assert f.calls == []


@pytest.mark.asyncio
async def test_brouter_url_uses_lon_lat_order():
    """BRouter URL must have `30.5,50.5|30.6,50.6` (LON-LAT order, NOT lat-lon)."""
    enricher = BrouterEnricher()
    f, rl = _ctx(status=200, body=b'{"features": []}')
    e = _entity()
    await enricher.enrich(e, EnrichmentContext(fetcher=f, rate_limiter=rl))
    assert len(f.calls) == 1
    url = f.calls[0]
    # entity.geom=(50.5, 30.5), attrs finish=(50.6, 30.6) → BRouter wants 30.5,50.5|30.6,50.6
    # urlencode() encodes ',' as %2C and '|' as %7C.
    assert "lonlats=30.5%2C50.5%7C30.6%2C50.6" in url
    assert "profile=river" in url
    assert "alternativeidx=0" in url
    assert "format=geojson" in url


@pytest.mark.asyncio
async def test_brouter_enricher_stamps_track_on_entity():
    enricher = BrouterEnricher()
    geojson = (
        b'{"type":"FeatureCollection","features":['
        b'{"type":"Feature","geometry":{"type":"LineString","coordinates":'
        b'[[30.5,50.5],[30.55,50.55],[30.6,50.6]]}}'
        b']}'
    )
    f, rl = _ctx(status=200, body=geojson)
    e = _entity()
    out = await enricher.enrich(e, EnrichmentContext(fetcher=f, rate_limiter=rl))
    assert out is not e
    assert "track" in out.attrs
    assert len(out.attrs["track"]) == 3
    assert out.attrs["track"][0] == (50.5, 30.5)  # lat, lon
    assert out.attrs["track_npts"] == 3
    assert out.attrs["track_quality"] == "sparse"  # npts=3 is sparse
    assert out.attrs["track_source"] == "brouter"


@pytest.mark.asyncio
async def test_brouter_enricher_quality_threshold_real():
    enricher = BrouterEnricher()
    coords = [[30.5, 50.5 + 0.001 * i] for i in range(15)]  # 15 pts → 'real'
    geojson = (
        b'{"type":"FeatureCollection","features":['
        + str.encode(
            '{"type":"Feature","geometry":{"type":"LineString","coordinates":'
            + str([[c[0], c[1]] for c in coords]).replace("'", "")
            + '}}'
        )
        + b']}'
    )
    f, rl = _ctx(status=200, body=geojson)
    e = _entity()
    out = await enricher.enrich(e, EnrichmentContext(fetcher=f, rate_limiter=rl))
    assert out.attrs["track_quality"] == "real"
    assert out.attrs["track_npts"] == 15


@pytest.mark.asyncio
async def test_brouter_enricher_silent_on_400():
    enricher = BrouterEnricher()
    f, rl = _ctx(status=400)
    e = _entity()
    out = await enricher.enrich(e, EnrichmentContext(fetcher=f, rate_limiter=rl))
    # No track stamped, but entity is returned unmodified.
    assert "track" not in out.attrs


@pytest.mark.asyncio
async def test_brouter_enricher_silent_on_empty_features():
    enricher = BrouterEnricher()
    f, rl = _ctx(status=200, body=b'{"features": []}')
    e = _entity()
    out = await enricher.enrich(e, EnrichmentContext(fetcher=f, rate_limiter=rl))
    assert "track" not in out.attrs


@pytest.mark.asyncio
async def test_brouter_enricher_silent_on_non_linestring():
    enricher = BrouterEnricher()
    f, rl = _ctx(
        status=200,
        body=b'{"features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[0,0]}}]}',
    )
    e = _entity()
    out = await enricher.enrich(e, EnrichmentContext(fetcher=f, rate_limiter=rl))
    assert "track" not in out.attrs


@pytest.mark.asyncio
async def test_brouter_enricher_skips_out_of_range_coords():
    enricher = BrouterEnricher()
    # GeoJSON has 1 valid point + 1 invalid
    geojson = (
        b'{"features":[{"type":"Feature","geometry":{"type":"LineString",'
        b'"coordinates":[[30.5,50.5],[200.0,30.0]]}}]}'
    )
    f, rl = _ctx(status=200, body=geojson)
    e = _entity()
    out = await enricher.enrich(e, EnrichmentContext(fetcher=f, rate_limiter=rl))
    # Only 1 valid coord < 2 → no track.
    assert "track" not in out.attrs


@pytest.mark.asyncio
async def test_brouter_enricher_real_safe_fetcher_works():
    """Integration check: real SafeFetcher with mock strategy can be substituted.

    Verifies the Enricher contract is satisfied by the real fetcher type.
    """
    import json

    enricher = BrouterEnricher()

    async def mock_strategy(url, headers):
        from parser_universal.types import FetchResult
        body_dict = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[30.5, 50.5], [30.6, 50.6]]}}
            ],
        }
        return FetchResult(
            url=url, status=200, body=json.dumps(body_dict).encode(), strategy="mock"
        )

    fetcher = SafeFetcher(strategies=[mock_strategy])

    class _R:
        async def acquire(self, *_a, **_k): pass
        def report(self, _s): pass

    e = _entity()
    out = await enricher.enrich(e, EnrichmentContext(fetcher=fetcher, rate_limiter=_R()))
    assert "track" in out.attrs
    assert len(out.attrs["track"]) == 2
