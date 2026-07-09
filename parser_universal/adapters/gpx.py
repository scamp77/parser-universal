"""GPX adapter — parses .gpx file or fetched .gpx content via gpxpy.

`locator` is either a local path or URL ending in `.gpx`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import gpxpy

from parser_universal.adapters.base import InputAdapter
from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.fetcher.strategies import httpx_strategy, jina_fallback
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter
from parser_universal.types import RawRecord

log = logging.getLogger(__name__)


class GPXAdapter:
    """Parse a GPX file or URL into a RawRecord with track_points."""

    source = "gpx"

    def source_safe_fetcher(self) -> SafeFetcher:
        return SafeFetcher(strategies=[httpx_strategy, jina_fallback])

    async def fetch_one(
        self,
        locator: str,
        *,
        fetcher: SafeFetcher,
        rate_limiter: AsyncRateLimiter,
    ) -> RawRecord | None:
        body: bytes | None = None
        if locator.startswith(("http://", "https://")):
            await rate_limiter.acquire()
            res = await fetcher.fetch(locator)
            rate_limiter.report(res.status)
            body = res.body
        else:
            p = Path(locator)
            if not p.exists():
                log.warning("gpx adapter: file not found: %s", locator)
                return None
            body = p.read_bytes()

        try:
            g = gpxpy.parse(body.decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            log.warning("gpx adapter: parse failed for %s: %s", locator, exc)
            return None

        track_points: list[tuple[float, float]] = []
        for track in g.tracks:
            for seg in track.segments:
                for pt in seg.points:
                    track_points.append((pt.latitude, pt.longitude))

        waypoints = [
            {
                "lat": w.latitude,
                "lon": w.longitude,
                "name": w.name or "",
                "type": w.type or "",
            }
            for w in g.waypoints
        ]

        return RawRecord(
            source=self.source,
            source_id=getattr(g, "name", None) or locator,
            raw={
                "name": getattr(g, "name", None),
                "description": getattr(g, "description", None),
                "track_points": track_points,
                "waypoints": waypoints,
            },
            raw_ref=locator,
            coord_hint=track_points[0] if track_points else None,
            fetched_at=datetime.now(timezone.utc),
        )
