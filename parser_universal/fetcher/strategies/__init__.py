"""Strategy implementations for SafeFetcher."""

from parser_universal.fetcher.strategies.httpx_impl import httpx_strategy
from parser_universal.fetcher.strategies.jina_fallback import jina_fallback

__all__ = ["httpx_strategy", "jina_fallback"]
