from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.fetcher.strategies.httpx_impl import httpx_strategy
from parser_universal.fetcher.strategies.jina_fallback import jina_fallback

__all__ = ["SafeFetcher", "httpx_strategy", "jina_fallback"]
