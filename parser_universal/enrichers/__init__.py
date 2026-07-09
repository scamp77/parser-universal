"""Enricher layer (Layer 3) — pluggable post-fetch enrichment.

Each enricher takes a DomainEntity and may return a (possibly mutated) copy
with extra fields. Pure functions preferred; idempotent re-runs are required
per the per-parser universal rule.
"""

from parser_universal.enrichers.base import Enricher
from parser_universal.enrichers.brouter import BrouterEnricher
from parser_universal.enrichers.coords import (
    canonicalize_osm_coords,
    parse_geojson_linestring,
)

__all__ = [
    "Enricher",
    "BrouterEnricher",
    "canonicalize_osm_coords",
    "parse_geojson_linestring",
]
