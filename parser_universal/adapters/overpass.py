"""OverpassAdapter — fetch OSM data via Overpass API.

Phase 3 deliverable. Pattern derived from:
  - /root/benz/parsers/osm_diff.py (URL=mail.ru, nwr+out center; brand classifier)
  - durable rules MEMORY-benz-phase-b-osm-diff-2026-07-06:
      * `nwr` not `node` (50% of fuel stations are ways/relations)
      * `out center;` (lat/lon order differs from placemarks — see enrichers/coords)
      * `maps.mail.ru` mirror (avoid `overpass-api.de` rate limits)

`locator` is an OverpassQL query string. The adapter POSTs it as the `data`
form field to the configured mirror.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

from parser_universal.adapters.base import InputAdapter
from parser_universal.enrichers.coords import canonicalize_osm_coords
from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.fetcher.strategies import httpx_strategy, jina_fallback
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter
from parser_universal.types import RawRecord

log = logging.getLogger(__name__)


# Default to maps.mail.ru mirror per benz durable rule.
DEFAULT_OVERPASS_URL = "https://maps.mail.ru/osm/tools/overpass/api/interpreter"


class OverpassAdapter:
    """Run an OverpassQL query and return the OSM elements as RawRecord(s).

    `locator` is the OverpassQL query body, e.g.:
        [out:json][timeout:180];
        area["ISO3166-1"="UA"]->.ua;
        nwr["amenity"="fuel"](area.ua);
        out center;
    """

    source = "overpass"

    def __init__(self, base_url: str = DEFAULT_OVERPASS_URL) -> None:
        self.base_url = base_url

    def source_safe_fetcher(self) -> SafeFetcher:
        """Return a fetcher for GET-style follow-up (rarely used).

        OverpassAdapter.fetch_one issues its own POST (not via SafeFetcher),
        because SafeFetcher assumes GET. This is fine — the adapter is the
        only specialized Layer-1 module that needs POST semantics.
        """
        return SafeFetcher(strategies=[httpx_strategy, jina_fallback])

    async def fetch_one(
        self,
        locator: str,
        *,
        fetcher: SafeFetcher,
        rate_limiter: AsyncRateLimiter,
    ) -> RawRecord | None:
        """POST `data=<locator>` to the mirror, parse elements.

        Returns ONE RawRecord wrapping the entire response. Downstream
        Normalizer splits it into N DomainEntities via `raw['elements']`.
        For batch OSM workloads (which is the usual case), this lets the
        orchestrator handle them as a single item.
        """
        await rate_limiter.acquire()
        body = urlencode({"data": locator}).encode("utf-8")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
                resp = await client.post(
                    self.base_url,
                    content=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("overpass_adapter: POST failed: %s", exc)
            rate_limiter.report(0)
            return None
        rate_limiter.report(resp.status_code)
        if resp.status_code >= 400:
            return None
        try:
            payload = json.loads(resp.content)
        except Exception as exc:  # noqa: BLE001
            log.warning("overpass_adapter: bad JSON: %s", exc)
            return None
        elements = payload.get("elements", [])
        if not elements:
            return RawRecord(
                source=self.source,
                source_id=locator[:120],
                raw={"query": locator, "elements": [], "raw_response": payload},
                raw_ref=self.base_url,
                fetched_at=datetime.now(timezone.utc),
            )
        return RawRecord(
            source=self.source,
            source_id=locator[:120],
            raw={
                "query": locator,
                "elements": elements,
                "n_elements": len(elements),
                "raw_response": payload,
            },
            raw_ref=self.base_url,
            coord_hint=canonicalize_osm_coords(elements[0]),
            fetched_at=datetime.now(timezone.utc),
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


__all__ = ["OverpassAdapter", "DEFAULT_OVERPASS_URL"]
