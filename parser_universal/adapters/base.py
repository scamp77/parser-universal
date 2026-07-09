"""Input adapter protocol — every adapter implements this."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from parser_universal.types import RawRecord
from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter


@runtime_checkable
class InputAdapter(Protocol):
    """Universal interface for an input adapter (one per source).

    Each adapter is a thin module that knows:
      - how to address a single item at the source (`locator` is adapter-defined)
      - how to parse the source-specific payload into RawRecord
      - which fetcher strategies to use (set on `source_safe_fetcher()`)
    """

    source: str

    async def fetch_one(
        self,
        locator,
        *,
        fetcher: SafeFetcher,
        rate_limiter: AsyncRateLimiter,
    ) -> RawRecord | None:
        """Fetch + parse one item. Returns None on skip (e.g. cache hit)."""
        ...

    def source_safe_fetcher(self) -> SafeFetcher:
        """Return a source-specific SafeFetcher (strategies curated for this source)."""
        ...
