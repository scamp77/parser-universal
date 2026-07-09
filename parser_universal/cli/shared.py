"""Shared CLI state — adapter + enricher registry."""

from parser_universal.adapters import (
    APIAdapter,
    GPXAdapter,
    HTMLAdapter,
    OverpassAdapter,
    SearXNGAdapter,
    URLCoordAdapter,
)
from parser_universal.enrichers import BrouterEnricher

ADAPTERS = {
    "url": URLCoordAdapter,
    "html": HTMLAdapter,
    "gpx": GPXAdapter,
    "api": APIAdapter,
    "overpass": OverpassAdapter,
    "searxng": SearXNGAdapter,
}

ENRICHERS = {
    "brouter": BrouterEnricher,
}

__all__ = ["ADAPTERS", "ENRICHERS"]
