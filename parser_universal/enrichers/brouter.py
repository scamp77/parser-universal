"""BrouterEnricher — fills DomainEntity.attrs['track'] from a BRouter route.

Mirrors sup-app/app/importers/brouter.py::route_via_brouter contract:
  - Default base URL: https://brouter.de/brouter
  - Profile: "river" (waterway routing)
  - Same 4-float signature: lon1, lat1, lon2, lat2 (LON-LAT order!)
  - Returns geojson; converts LineString coordinates [lon, lat] → (lat, lon)
  - Stamps `attrs['track_quality']` per parser-universal contract
  - Failure-tolerant: missing track → keep geom, leave attrs untouched

Benz durable rule: profile `river` for waterway; track npts classifiers
(<2=placeholder, <=10=sparse, >10=real) mirror sup-app classify_track_quality.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from parser_universal.enrichers.base import Enricher, EnrichmentContext
from parser_universal.enrichers.coords import parse_geojson_linestring
from parser_universal.types import DomainEntity, FetchResult

log = logging.getLogger(__name__)


DEFAULT_BROUTER_URL = "https://brouter.de/brouter"
DEFAULT_PROFILE = "river"


def classify_track_quality(npts: int) -> str:
    """Bench-matched to sup-app/app/importers/brouter.py:52.

      npts <= 0  -> 'unknown'
      npts == 2  -> 'placeholder' (straight line)
      npts <= 10 -> 'sparse'
      npts  > 10 -> 'real'
    """
    if npts <= 0:
        return "unknown"
    if npts == 2:
        return "placeholder"
    if npts <= 10:
        return "sparse"
    return "real"


@dataclass
class BrouterTrackResult:
    """Result returned by BrouterEnricher.enrich."""

    npts: int
    quality: str
    error: str | None = None


class BrouterEnricher:
    """Layer-3 enricher: BRouter → entity.attrs['track']"""

    name = "brouter"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BROUTER_URL,
        profile: str = DEFAULT_PROFILE,
        timeout_s: float = 45.0,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url
        self.profile = profile
        self.timeout_s = timeout_s
        self.max_retries = max_retries

    async def enrich(
        self, entity: DomainEntity, ctx: EnrichmentContext
    ) -> DomainEntity:
        """Call BRouter for the two endpoints of the entity and stamp result.

        Endpoints:
          - If entity.geom is set and entity.attrs.get('finish_lon/lat') is set,
            use those 2 points.
          - If only entity.geom is set, treat it as a single point and skip
            (BRouter needs 2 endpoints).
        """
        if entity.geom is None:
            return entity
        attrs = dict(entity.attrs)
        # Coordinates: BRouter wants LON-LAT order. entity.geom is (lat, lon).
        lat1, lon1 = entity.geom
        # Look for a finish coordinate in attrs; default to a 0.1° offset.
        finish = (attrs.get("finish_lat"), attrs.get("finish_lon"))
        if finish[0] is None or finish[1] is None:
            log.debug("brouter: skipping, no finish coord for %s/%s", entity.source, entity.source_id)
            return entity
        lat2, lon2 = finish  # (lat, lon)
        # Convert to BRouter's lon-lat order.
        url = self._build_url(lon1, lat1, lon2, lat2)
        try:
            result = await self._fetch_with_retry(url, ctx)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "brouter_enricher: %s/%s: %s",
                entity.source,
                entity.source_id,
                exc,
            )
            return entity
        if result is None:
            return entity

        coords = parse_geojson_linestring(result)
        if len(coords) < 2:
            return entity
        attrs["track"] = coords
        attrs["track_npts"] = len(coords)
        attrs["track_quality"] = classify_track_quality(len(coords))
        attrs["track_source"] = "brouter"
        from dataclasses import replace
        return replace(entity, attrs=attrs)

    def _build_url(
        self, lon1: float, lat1: float, lon2: float, lat2: float
    ) -> str:
        # BRouter pipe-separated lonlats, altidx 0, geojson format.
        params = urlencode(
            {
                "lonlats": f"{lon1},{lat1}|{lon2},{lat2}",
                "profile": self.profile,
                "alternativeidx": "0",
                "format": "geojson",
            }
        )
        return f"{self.base_url}?{params}"

    async def _fetch_with_retry(
        self, url: str, ctx: EnrichmentContext
    ) -> list | None:
        """Fetch BRouter GeoJSON via the supplied SafeFetcher.

        Returns the LineString `coordinates` list, or None on failure.
        No retry here — SafeFetcher already retries per its RetryPolicy.
        """
        await ctx.rate_limiter.acquire()
        res: FetchResult = await ctx.fetcher.fetch(url)
        ctx.rate_limiter.report(res.status)
        if res.status == 400 or res.status == 404:
            return None
        if res.status >= 400:
            return None
        import json as _json
        try:
            data = _json.loads(res.body)
        except Exception:  # noqa: BLE001
            return None
        feats = data.get("features", [])
        if not feats:
            return None
        geom = feats[0].get("geometry", {})
        if geom.get("type") != "LineString":
            return None
        return geom.get("coordinates", [])


__all__ = [
    "BrouterEnricher",
    "BrouterTrackResult",
    "classify_track_quality",
    "DEFAULT_BROUTER_URL",
    "DEFAULT_PROFILE",
]
