"""Supported bbox — copy from sup-app/scripts/import_route/parsers.py.

IMPORTANT: order matters. KZ and UA must be checked BEFORE RU, because
RU bbox covers almost everything and would swallow KZ/UA points otherwise.
"""

from __future__ import annotations

SUPPORTED_BBOX: dict[str, tuple[float, float, float, float]] = {
    "BY": (51.0, 23.0, 56.5, 33.0),
    "KZ": (40.0, 46.0, 56.0, 88.0),
    "UA": (44.0, 22.0, 53.0, 41.0),
    "RU": (41.0, 19.0, 82.0, 180.0),
}


def detect_country(lat: float, lon: float) -> str:
    """Return ISO-2 country code if (lat, lon) is in any SUPPORTED_BBOX; else 'unknown'."""
    for cc, (mn, mo, mx, xo) in SUPPORTED_BBOX.items():
        if mn <= lat <= mx and mo <= lon <= xo:
            return cc
    return "unknown"


def in_supported_region(lat: float, lon: float) -> bool:
    """True if (lat, lon) is inside any SUPPORTED_BBOX."""
    return detect_country(lat, lon) != "unknown"
