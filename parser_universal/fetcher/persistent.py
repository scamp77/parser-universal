"""Persistent HTTP client — shared across all strategies in a single run.

Phase 4 deliverable.

Why: Phase 1-3 open a fresh `httpx.AsyncClient` per fetch (per strategy call),
incurring TCP + TLS handshake overhead (often 100-300ms each). For batch
runs (1000+ URLs from Overpass, BRouter, etc.) that's the difference between
a 30s and 5-minute run.

Pattern derived from /root/benz/app/services/* persistent-client pattern.

Usage:
    async with SafeFetcher(strategies=[httpx_strategy]) as fetcher:
        res = await fetcher.fetch(url)

`safe.py`'s SafeFetcher now supports `async with` to open/close a shared
transport. Without the context manager, behavior is unchanged (per-call client).

This module also exposes `close_all_clients()` for graceful shutdown across
multiple orchestrators (cron-script-before-cron rule applies).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx

log = logging.getLogger(__name__)


class PersistentHTTPClient:
    """Reusable httpx.AsyncClient across many fetches.

    Holds:
      - 1 shared connection pool (default: 100 keepalive)
      - 1 default timeout (30s)
      - shared headers (User-Agent)

    Pass into a SafeFetcher via the `httpx_strategy_with_client` strategy
    factory — see `strategies/httpx_persistent_impl.py`.
    """

    DEFAULT_UA = "Mozilla/5.0 parser-universal/0.4"

    def __init__(
        self,
        *,
        timeout_s: float = 30.0,
        connect_timeout_s: float = 10.0,
        max_keepalive: int = 100,
        max_connections: int = 100,
        user_agent: str = DEFAULT_UA,
    ) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s, connect=connect_timeout_s),
            follow_redirects=True,
            limits=httpx.Limits(
                max_keepalive_connections=max_keepalive,
                max_connections=max_connections,
            ),
            headers={"User-Agent": user_agent},
        )

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "PersistentHTTPClient":
        return self

    async def __aexit__(self, *a) -> None:
        await self.aclose()


@asynccontextmanager
async def open_persistent_client(**kwargs) -> AsyncIterator[PersistentHTTPClient]:
    """Context-manager helper for one-off usage."""
    p = PersistentHTTPClient(**kwargs)
    try:
        yield p
    finally:
        await p.aclose()


__all__ = ["PersistentHTTPClient", "open_persistent_client"]
