from parser_universal.adapters.base import InputAdapter
from parser_universal.adapters.url_dispatch import URLCoordAdapter
from parser_universal.adapters.html import HTMLAdapter
from parser_universal.adapters.gpx import GPXAdapter
from parser_universal.adapters.api import APIAdapter
from parser_universal.adapters.overpass import OverpassAdapter, DEFAULT_OVERPASS_URL
from parser_universal.adapters.searxng import SearXNGAdapter, DEFAULT_SEARXNG_URL

__all__ = [
    "InputAdapter",
    "URLCoordAdapter",
    "HTMLAdapter",
    "GPXAdapter",
    "APIAdapter",
    "OverpassAdapter",
    "DEFAULT_OVERPASS_URL",
    "SearXNGAdapter",
    "DEFAULT_SEARXNG_URL",
]
