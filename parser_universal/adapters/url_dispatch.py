"""Yandex/Google/OSM/BRouter URL → (lat, lon) pairs.

Self-contained adapter: parses URL-only (no HTTP). The actual HTTP layer is
handled by SafeFetcher when an adapter wants to fetch the URL behind the link.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from parser_universal.adapters.base import InputAdapter
from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.fetcher.strategies import httpx_strategy, jina_fallback
from parser_universal.normalizers.coord_canonical import parse_url_to_coords
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter
from parser_universal.types import RawRecord

log = logging.getLogger(__name__)


class URLCoordAdapter:
    """URL-only adapter: parses a URL into (lat, lon) pairs.

    `locator` is a URL string. `fetch_one` does not actually fetch — it
    parses the URL. (Reason: URL parsing is fast; SafeFetcher reserved for
    follow-up hydration if the URL points to a HTML page.)
    """

    source = "url"

    def source_safe_fetcher(self) -> SafeFetcher:
        """Return a fetcher for follow-up hydration (rarely used)."""
        return SafeFetcher(strategies=[httpx_strategy, jina_fallback])

    async def fetch_one(
        self,
        locator: str,
        *,
        fetcher: SafeFetcher,
        rate_limiter: AsyncRateLimiter,
    ) -> RawRecord | None:
        points = parse_url_to_coords(locator)
        if not points:
            return None
        return RawRecord(
            source=self.source,
            source_id=locator,
            raw={"url": locator, "points": points},
            raw_ref=locator,
            coord_hint=points[0],
            fetched_at=datetime.now(timezone.utc),
        )
