"""Default httpx-based fetch strategy. Cheap baseline; OK for open APIs."""

from __future__ import annotations

import logging
import time

import httpx

from parser_universal.types import FetchResult

log = logging.getLogger(__name__)


async def httpx_strategy(url: str, headers: dict | None = None) -> FetchResult:
    """Plain httpx GET. Sets a Chrome-like UA by default."""
    merged_headers = {"User-Agent": "Mozilla/5.0 parser-universal/0.1"}
    if headers:
        merged_headers.update(headers)
    t0 = time.monotonic()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        resp = await client.get(url, headers=merged_headers)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return FetchResult(
        url=url,
        status=resp.status_code,
        body=resp.content,
        headers=dict(resp.headers),
        elapsed_ms=elapsed_ms,
        strategy="httpx",
    )
