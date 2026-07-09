"""Jina Reader fallback strategy.

Free proxy: r.jina.ai/{url}. Returns markdown rendition of the page;
bypasses most Cloudflare / DataDome bot-detection. Last-resort.
"""

from __future__ import annotations

import logging
import time

import httpx

from parser_universal.types import FetchResult

log = logging.getLogger(__name__)


async def jina_fallback(url: str, headers: dict | None = None) -> FetchResult:
    """Fetch via r.jina.ai. Polite sleep per sup-app T1.4 PR #74 jina_retry pattern."""
    jina_url = f"https://r.jina.ai/{url}"
    merged_headers = {
        "Accept": "text/plain",
        "X-Return-Format": "markdown",
    }
    if headers:
        merged_headers.update(headers)
    t0 = time.monotonic()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=8.0),
        follow_redirects=True,
    ) as client:
        resp = await client.get(jina_url, headers=merged_headers)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return FetchResult(
        url=url,
        status=resp.status_code,
        body=resp.content,
        headers=dict(resp.headers),
        elapsed_ms=elapsed_ms,
        strategy="jina_fallback",
    )
