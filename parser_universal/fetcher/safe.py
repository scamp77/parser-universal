"""Multi-strategy fetcher with retry + fallback chain.

Tries configured strategies in order; first 2xx wins.
On exhaustion, applies RetryPolicy before retrying the chain.

Phase 1 strategies:
  1. httpx (baseline)
  2. curl_cffi (TLS impersonation)  [optional dep]
  3. jina_fallback (r.jina.ai/{url}) [$0, bypasses most bot-detection]
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from parser_universal.types import FetchResult, RetryPolicy, DEFAULT_RETRY

log = logging.getLogger(__name__)

StrategyFn = Callable[[str, dict | None], Awaitable[FetchResult]]


class SafeFetcher:
    """Try strategies in order; first 2xx wins. Apply RetryPolicy on exhaustion."""

    def __init__(
        self,
        strategies: list[StrategyFn],
        retry: RetryPolicy = DEFAULT_RETRY,
    ) -> None:
        if not strategies:
            raise ValueError("SafeFetcher needs at least one strategy")
        self.strategies = strategies
        self.retry = retry

    async def fetch(self, url: str, headers: dict | None = None) -> FetchResult:
        """Fetch `url`, trying strategies and retrying per RetryPolicy."""
        attempt = 0
        last_exc: Exception | None = None
        while attempt <= self.retry.max_retries:
            attempt += 1
            for strat in self.strategies:
                try:
                    res = await strat(url, headers)
                    if 200 <= res.status < 400:
                        return res
                    log.info(
                        "fetcher: %s returned %d for %s",
                        res.strategy,
                        res.status,
                        url,
                    )
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    log.debug("fetcher: strategy raised: %s", exc)
            # All strategies failed or returned non-2xx. Backoff + retry.
            if attempt <= self.retry.max_retries:
                wait = self.retry.initial_backoff_s * (
                    self.retry.backoff_factor ** (attempt - 1)
                )
                log.warning(
                    "fetcher: all strategies failed for %s; retry %d/%d in %.1fs",
                    url,
                    attempt,
                    self.retry.max_retries,
                    wait,
                )
                await asyncio.sleep(wait)
        # Out of retries.
        msg = f"all strategies exhausted for {url}"
        if last_exc:
            raise RuntimeError(msg) from last_exc
        raise RuntimeError(msg)
