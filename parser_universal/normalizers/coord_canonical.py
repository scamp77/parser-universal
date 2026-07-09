"""Coord canonicalization.

Two-stage:
  1. extract_coord_pairs(text)    — DMS first (more specific), then decimal
  2. parse_url_to_coords(url)     — Yandex/Google/OSM/BRouter param quirks

Source: copy from sup-app/scripts/import_route/parsers.py (488 LOC).
We extract only the canonical-shape parts (no `ParsedInput` dataclass — that's
sup-app specific).
"""

from __future__ import annotations

import re
from typing import Final
from urllib.parse import parse_qs, urlparse


RE_DECIMAL_PAIR: Final = re.compile(
    r"(?P<lat>-?\d{1,3}[.,]\d{3,7})[,\s]+(?P<lon>-?\d{1,3}[.,]\d{3,7})"
)
RE_DMS_PAIR: Final = re.compile(
    r'(?P<lat_d>\d{1,3})[°\s]+(?P<lat_m>\d{1,2})[\'′\s]+(?P<lat_s>[\d.,]+)?["″\s]*'
    r"(?P<lat_h>[NSNnSs])[,\s]+"
    r'(?P<lon_d>\d{1,3})[°\s]+(?P<lon_m>\d{1,2})[\'′\s]+(?P<lon_s>[\d.,]+)?["″\s]*'
    r"(?P<lon_h>[EeWw])"
)


def _dms_to_decimal(d: str, m: str, s: str | None, hemi: str) -> float:
    """Convert degree/minute/second (+ hemisphere) → decimal degrees."""
    val = float(d) + float(m) / 60.0
    if s:
        val += float(s.replace(",", ".")) / 3600.0
    if hemi.upper() in "SW":
        val = -val
    return val


def extract_coord_pairs(text: str) -> list[tuple[float, float]]:
    """Return up to 2 unique (lat, lon) pairs found in text.

    Tries DMS first (more specific), then decimal. Dedupes consecutive.
    """
    pairs: list[tuple[float, float]] = []

    for m in RE_DMS_PAIR.finditer(text):
        try:
            lat = _dms_to_decimal(m["lat_d"], m["lat_m"], m["lat_s"], m["lat_h"])
            lon = _dms_to_decimal(m["lon_d"], m["lon_m"], m["lon_s"], m["lon_h"])
            pairs.append((lat, lon))
        except (ValueError, KeyError):
            continue

    if not pairs:
        for m in RE_DECIMAL_PAIR.finditer(text):
            try:
                lat = float(m["lat"].replace(",", "."))
                lon = float(m["lon"].replace(",", "."))
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    pairs.append((lat, lon))
            except ValueError:
                continue

    unique: list[tuple[float, float]] = []
    for p in pairs:
        if not unique or unique[-1] != p:
            unique.append(p)
    return unique[:2]


# === URL parsing quirks ===
# Yandex Maps: ?ll=37.6173,55.7558 OR ?pt=37.6173,55.7558  (LON,LAT order!)
# Google Maps: @55.7558,37.6173,15z  or  ?q=55.7558,37.6173  (LAT,LON)
# OSM: ?mlat=55.7558&mlon=37.6173
# BRouter: #lonlats=27.5,53.9;27.6,53.8&profile=river


def _parse_yandex(qs: str) -> list[tuple[float, float]]:
    """Yandex: aggregate ll=, pt=, q= params. Yandex uses LON,LAT order."""
    params = parse_qs(qs)
    points: list[tuple[float, float]] = []
    for key in ("ll", "pt", "q"):
        if key in params:
            v = params[key][0]
            if "," in v:
                try:
                    a, b = v.split(",", 1)
                    lon, lat = float(a), float(b)
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        points.append((lat, lon))
                except ValueError:
                    pass
    return points


def _parse_google(url: str, qs: str) -> list[tuple[float, float]]:
    """Google: ?q=lat,lon OR @lat,lon,zoom in path."""
    params = parse_qs(qs)
    if "q" in params:
        v = params["q"][0]
        if "," in v:
            try:
                lat, lon = (float(x) for x in v.split(",", 1))
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return [(lat, lon)]
            except ValueError:
                pass
    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+),", url)
    if m:
        try:
            lat, lon = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return [(lat, lon)]
        except ValueError:
            pass
    return []


def _parse_osm(qs: str) -> list[tuple[float, float]]:
    """OSM permalink: ?mlat=&mlon="""
    params = parse_qs(qs)
    if "mlat" in params and "mlon" in params:
        try:
            return [(float(params["mlat"][0]), float(params["mlon"][0]))]
        except ValueError:
            pass
    return []


def _parse_brouter(url: str) -> list[tuple[float, float]]:
    """BRouter: #lonlats=27.5,53.9;27.6,53.8&profile=river (LON,LAT order!)."""
    if "#" in url:
        fragment = url.split("#", 1)[1]
    else:
        fragment = url
    params = parse_qs(fragment)
    lonlats = params.get("lonlats", [""])[0]
    if not lonlats:
        return []
    points: list[tuple[float, float]] = []
    for piece in lonlats.split(";"):
        if "," not in piece:
            continue
        try:
            a, b = piece.split(",", 1)
            lon, lat = float(a), float(b)
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                points.append((lat, lon))
        except ValueError:
            continue
    return points


def parse_url_to_coords(url: str) -> list[tuple[float, float]]:
    """Dispatch URL → list of (lat, lon) by domain. Empty list if unknown."""
    parsed = urlparse(url)
    qs = parsed.query
    host = (parsed.netloc or "").lower()

    if "yandex" in host:
        return _parse_yandex(qs)
    if "google" in host:
        return _parse_google(url, qs)
    if "openstreetmap" in host or "osm" in host:
        return _parse_osm(qs)
    if "brouter" in host:
        return _parse_brouter(url)
    return []
