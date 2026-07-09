"""JSON API adapter — generic JSON HTTP endpoint.

Passes through the JSON payload as `raw`. `locator` is a URL; optional
JSONPath-like selector is left to downstream consumers.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from parser_universal.adapters.base import InputAdapter
from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.fetcher.strategies import httpx_strategy, jina_fallback
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter
from parser_universal.types import RawRecord

log = logging.getLogger(__name__)


class APIAdapter:
    """Generic JSON API adapter.

    `locator` is a URL; optional `headers` are passed through (auth tokens).
    """

    source = "api"

    def source_safe_fetcher(self) -> SafeFetcher:
        return SafeFetcher(
            strategies=[httpx_strategy, jina_fallback],
        )

    async def fetch_one(
        self,
        locator: str,
        *,
        fetcher: SafeFetcher,
        rate_limiter: AsyncRateLimiter,
        headers: dict | None = None,
    ) -> RawRecord | None:
        await rate_limiter.acquire()
        res = await fetcher.fetch(locator, headers=headers)
        rate_limiter.report(res.status)
        try:
            payload = json.loads(res.body)
        except json.JSONDecodeError as exc:
            log.warning("api adapter: JSON parse failed for %s: %s", locator, exc)
            return None
        return RawRecord(
            source=self.source,
            source_id=locator,
            raw={"json": payload, "headers": dict(res.headers), "strategy": res.strategy},
            raw_ref=locator,
            fetched_at=datetime.now(timezone.utc),
        )
