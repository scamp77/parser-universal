"""SearXNGAdapter — search-discovery via self-hosted SearXNG JSON API.

Use case: discovery layer in pipelines that don't know URLs in advance
(e.g. finding new UA fuel-infrastructure sources, finding pages about a
specific incident). Pattern mirrors OverpassAdapter but issues a GET
instead of POST.

SearXNG JSON response shape (simplified):
    {
      "query": "...",
      "results": [
        {
          "url":         "https://...",
          "title":       "...",
          "content":     "...",
          "engine":      "google",
          "parsed_url":  ["https", "..."],
          "score":       0.95,
          "category":    "general",
          "publishedDate": "2026-07-05T...",
          "metadata":    "..."
        }
      ],
      "number_of_results": 42
    }

`locator` is a SearXNG search query (not a URL). The adapter builds the
GET request from `base_url?q=<locator>&format=json&...` and parses the
JSON envelope into one RawRecord per result.

Source-server convention per durable memory (ses_0ea82b8e4...notes.md):
    GET http://localhost:8080/search
        ?q=<locator>
        &format=json
        &language=ru          # optional
        &time_range=day      # optional: day|week|month|year
        &safesearch=0         # optional
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlencode

import httpx

from parser_universal.adapters.base import InputAdapter
from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.fetcher.strategies import httpx_strategy, jina_fallback
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter
from parser_universal.types import RawRecord

log = logging.getLogger(__name__)

# Default to local self-hosted SearXNG per allrivers_parser convention.
DEFAULT_SEARXNG_URL = "http://localhost:8080/search"


class SearXNGAdapter:
    """Run a SearXNG query and return one RawRecord per result.

    `locator` is a SearXNG query string (free text, URL-encoded by the
    adapter). The adapter normalises the result list under a single
    RawRecord; downstream consumers split on `raw['results']`.

    Example:
        adapter.fetch_one("OKKO ціни Чернігів", fetcher=..., rate_limiter=...)
    """

    source = "searxng"

    def __init__(
        self,
        base_url: str = DEFAULT_SEARXNG_URL,
        language: str = "ru",
        time_range: str | None = None,
        safesearch: int = 0,
        max_results: int = 20,
        timeout_s: float = 30.0,
        engines: list[str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.language = language
        # SearXNG accepts: day | week | month | year. Empty/None = no filter.
        self.time_range = time_range
        self.safesearch = safesearch
        self.max_results = max_results
        self.timeout_s = timeout_s
        # Optional list of engine names to restrict the search to.
        # Useful when the local SearXNG instance has unresponsive
        # default engines — pass `["bing","duckduckgo","google"]` to
        # skip the ones that error out on every query.
        self.engines = engines

    def source_safe_fetcher(self) -> SafeFetcher:
        """SearXNG is a self-hosted JSON API — SafeFetcher not used in
        `fetch_one` (we issue a direct GET to keep ?format=json semantics
        simple). Returns a default fetcher for follow-up URL hydration.
        """
        return SafeFetcher(strategies=[httpx_strategy, jina_fallback])

    def _build_url(self, query: str) -> str:
        params: dict[str, str] = {
            "q": quote_plus(query),
            "format": "json",
            "language": self.language,
            "safesearch": str(self.safesearch),
        }
        if self.time_range:
            params["time_range"] = self.time_range
        if self.engines:
            params["engines"] = ",".join(self.engines)
        return f"{self.base_url}?{urlencode(params)}"

    async def fetch_one(
        self,
        locator: str,
        *,
        fetcher: SafeFetcher,
        rate_limiter: AsyncRateLimiter,
    ) -> RawRecord | None:
        """GET SearXNG JSON for the query, return all results as RawRecord."""
        await rate_limiter.acquire()
        url = self._build_url(locator)
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_s)
            ) as client:
                resp = await client.get(url)
        except Exception as exc:  # noqa: BLE001
            log.warning("searxng_adapter: GET failed: %s", exc)
            rate_limiter.report(0)
            return None
        rate_limiter.report(resp.status_code)
        if resp.status_code >= 400:
            log.warning("searxng_adapter: HTTP %s for %s", resp.status_code, locator)
            return None
        try:
            payload = json.loads(resp.content)
        except Exception as exc:  # noqa: BLE001
            log.warning("searxng_adapter: bad JSON for %s: %s", locator, exc)
            return None

        results = (payload.get("results") or [])[: self.max_results]
        return RawRecord(
            source=self.source,
            source_id=f"searxng:{hash(locator) & 0xFFFFFFFF:#x}",
            raw={
                "query": locator,
                "n_results": len(results),
                "number_of_results": payload.get("number_of_results"),
                "results": results,
                "raw_response": payload,
                "engine_url": url,
            },
            raw_ref=url,
            fetched_at=datetime.now(timezone.utc),
            text=(results[0]["content"] if results and results[0].get("content") else None),
        )

    async def fetch_batch(
        self,
        locators: list[str],
        *,
        fetcher: SafeFetcher,
        rate_limiter: AsyncRateLimiter,
    ) -> list[RawRecord]:
        """Batched variant — returns list of RawRecord, one per locator."""
        out: list[RawRecord] = []
        for q in locators:
            r = await self.fetch_one(q, fetcher=fetcher, rate_limiter=rate_limiter)
            if r is not None:
                out.append(r)
        return out


__all__ = ["SearXNGAdapter", "DEFAULT_SEARXNG_URL"]
