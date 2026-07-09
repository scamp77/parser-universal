"""Coord canonicalization for OSM elements + GeoJSON LineString parsing.

This module fixes two known pain points (benz durable rules):

1. **OSM Overpass output uses different lat/lon order conventions**:
   - `element.center = {lat, lon}`     -> [LAT, LON] order
   - `element.tags['..placemarks']`     -> {'LON': ..., 'LAT': ...}

   We canonicalize everything to `Entity.geom = (lat, lon)` consistent with
   parser-universal's domain model (and parser_universal.normalizers.bbox).

2. **GeoJSON LineString coordinates are `[lon, lat]`** per RFC 7946. We accept
   that on the wire and convert to `(lat, lon)` tuples in memory.

Verified against /root/sup-app/scripts/import_route/track.py patterns.
"""

from __future__ import annotations

from typing import Any


def parse_geojson_linestring(coords: list) -> list[tuple[float, float]]:
    """Convert GeoJSON LineString coords [[lon, lat], ...] → [(lat, lon), ...].

    Returns an empty list if `coords` is empty / not a list / not numeric.
    """
    out: list[tuple[float, float]] = []
    for c in coords:
        if not isinstance(c, (list, tuple)) or len(c) < 2:
            continue
        try:
            lon, lat = float(c[0]), float(c[1])
        except (TypeError, ValueError):
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            out.append((lat, lon))
    return out


def canonicalize_osm_coords(elem: dict) -> tuple[float, float] | None:
    """Pull a (lat, lon) tuple from one OSM element.

    Tries in order:
      1. `elem['center'] = {'lat': ..., 'lon': ...}` (ways/relations, out center;)

         >>> import json
         >>> j = json.dumps({'center': {'lat': 50.5, 'lon': 30.5}, 'lat': None, 'lon': None})
         >>> len(j)

      2. `elem['lat'] / elem['lon']` (nodes)
      3. None

    The OSM Overpass API returns TWO different orderings in a single response,
    depending on which field is populated (benz rule #discovered-2026-07-02:
    "center и placemarks используют РАЗНЫЙ порядок"). This helper always
    returns the canonical (lat, lon) tuple used inside parser-universal.

    Args:
        elem: a single OSM element dict (node, way, or relation).

    Returns:
        (lat, lon) tuple, or None if no coord is present.
    """
    # 1. 'center' key — applies to ways/relations with 'out center;'.
    center = elem.get("center")
    if isinstance(center, dict):
        try:
            lat = float(center.get("lat"))
            lon = float(center.get("lon"))
        except (TypeError, ValueError):
            pass
        else:
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon)
    # 2. flat 'lat' / 'lon' (nodes).
    try:
        lat = float(elem["lat"])
        lon = float(elem["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return (lat, lon)
    return None


__all__ = ["parse_geojson_linestring", "canonicalize_osm_coords"]
