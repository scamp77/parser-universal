"""Async (asyncio) implementation of the same algorithm as sync_impl.RateLimiter."""

from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger(__name__)


class AsyncRateLimiter:
    """Async version of RateLimiter — uses asyncio.Lock instead of threading.

    Same semantics:
      - token bucket with rate_per_sec, burst
      - on 429/5xx: double interval (max 60s)
      - on 2xx: relax every 30s
    """

    _BACKOFF_STATUSES = {429, 500, 502, 503, 504}

    def __init__(self, rate_per_sec: float = 2.0, burst: int = 4) -> None:
        self.base_interval = 1.0 / rate_per_sec
        self.burst = burst
        self.tokens = float(burst)
        self.last_refill = time.monotonic()
        self.current_interval = self.base_interval
        self._lock = asyncio.Lock()
        self._last_success = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(
            self.burst,
            self.tokens + elapsed / self.current_interval,
        )
        self.last_refill = now

    async def acquire(self, timeout: float = 120.0) -> None:
        """Block until a token is available. Raises asyncio.TimeoutError on timeout."""
        deadline = time.monotonic() + timeout
        while True:
            async with self._lock:
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = self.current_interval * (1.0 - self.tokens)
            if time.monotonic() + wait > deadline:
                raise asyncio.TimeoutError("async rate limiter: timeout waiting for token")
            await asyncio.sleep(min(wait, 1.0))

    def report(self, status_code: int) -> None:
        """Feed back HTTP status to adjust the rate. Synchronous — fast, no I/O."""
        # NOTE: report() never blocks on the lock. We accept minor token-bucket
        # races here since `report()` is only advisory.
        if status_code in self._BACKOFF_STATUSES:
            old = self.current_interval
            self.current_interval = min(60.0, self.current_interval * 2.0)
            self.tokens = 0.0
            if old != self.current_interval:
                log.warning(
                    "rate: HTTP %d, backing off to %.2fs/request",
                    status_code,
                    self.current_interval,
                )
        else:
            now = time.monotonic()
            if now - self._last_success > 30.0:
                new = max(self.base_interval, self.current_interval * 0.5)
                if new != self.current_interval:
                    log.info("rate: relaxing to %.2fs/request", new)
                    self.current_interval = new
            self._last_success = now
