"""HTML adapter — static HTML pages. BeautifulSoup + curl_cffi.

Tries `httpx` by default; for bot-protected sources add `curl_cffi` strategy.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from parser_universal.adapters.base import InputAdapter
from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.fetcher.strategies import httpx_strategy, jina_fallback
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter
from parser_universal.types import RawRecord

log = logging.getLogger(__name__)


class HTMLAdapter:
    """Fetch + parse a single static HTML page.

    `locator` is a URL. Selector is applied via `attrs={'selector': '...'}`
    on the orchestrator config layer; for now we return the full soup as raw.
    """

    source = "html"

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
    ) -> RawRecord | None:
        await rate_limiter.acquire()
        res = await fetcher.fetch(locator)
        rate_limiter.report(res.status)
        # Parse body as HTML.
        try:
            soup = BeautifulSoup(res.body, "lxml")
            text = soup.get_text(separator="\n", strip=True)
            title = soup.title.get_text(strip=True) if soup.title else ""
        except Exception as exc:  # noqa: BLE001
            log.warning("html adapter: parse failed: %s", exc)
            text = ""
            title = ""
        return RawRecord(
            source=self.source,
            source_id=locator,
            raw={
                "title": title,
                "body": res.body,
                "headers": dict(res.headers),
                "strategy": res.strategy,
            },
            raw_ref=locator,
            text=text[:50_000] if text else None,
            fetched_at=datetime.now(timezone.utc),
        )
