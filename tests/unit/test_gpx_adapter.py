"""Unit tests for GPX adapter (offline, file-based)."""

import asyncio
from pathlib import Path

from parser_universal.adapters.gpx import GPXAdapter


def test_gpx_adapter_parses_local_file():
    sample = Path(__file__).parent.parent / "data" / "sample.gpx"
    assert sample.exists(), f"sample fixture missing: {sample}"
    adapter = GPXAdapter()
    fetcher = adapter.source_safe_fetcher()

    class _NoOpRL:
        async def acquire(self, *_a, **_k):
            return None

        def report(self, _status):
            return None

    async def run():
        return await adapter.fetch_one(str(sample), fetcher=fetcher, rate_limiter=_NoOpRL())

    rec = asyncio.run(run())
    assert rec is not None
    assert rec.source == "gpx"
    track_points = rec.raw["track_points"]
    assert len(track_points) == 3
    assert track_points[0] == (55.7558, 37.6173)
    assert len(rec.raw["waypoints"]) == 2
    assert rec.coord_hint == (55.7558, 37.6173)


def test_gpx_adapter_missing_file_returns_none():
    adapter = GPXAdapter()
    fetcher = adapter.source_safe_fetcher()

    class _NoOpRL:
        async def acquire(self, *_a, **_k):
            return None

        def report(self, _status):
            return None

    async def run():
        return await adapter.fetch_one("/nonexistent/path.gpx", fetcher=fetcher, rate_limiter=_NoOpRL())

    assert asyncio.run(run()) is None
