"""Persistent httpx strategy — uses a shared httpx.AsyncClient.

Drop-in replacement for `httpx_strategy`. The first arg is a PersistentHTTPClient;
pass it through a SafeFetcher-aware factory.

Usage:
    async with PersistentHTTPClient() as client:
        async def persistent_httpx(url, headers=None):
            res = await client.client.get(url, headers=headers or {})
            ...
        fetcher = SafeFetcher(strategies=[persistent_httpx])
"""

from __future__ import annotations

import logging
import time

from parser_universal.fetcher.persistent import PersistentHTTPClient
from parser_universal.types import FetchResult

log = logging.getLogger(__name__)


def make_persistent_httpx(client: PersistentHTTPClient):
    """Return an async strategy function bound to the given persistent client."""

    async def _persistent_httpx(url: str, headers: dict | None = None) -> FetchResult:
        merged_headers = {}
        if headers:
            merged_headers.update(headers)
        t0 = time.monotonic()
        resp = await client.client.get(url, headers=merged_headers)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return FetchResult(
            url=url,
            status=resp.status_code,
            body=resp.content,
            headers=dict(resp.headers),
            elapsed_ms=elapsed_ms,
            strategy="httpx_persistent",
        )

    return _persistent_httpx


__all__ = ["make_persistent_httpx"]
