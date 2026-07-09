"""Enricher protocol + tiny dataclass for enrichment context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter
from parser_universal.types import DomainEntity


@dataclass
class EnrichmentContext:
    """Shared infra passed to every enricher (Layer 3)."""

    fetcher: SafeFetcher
    rate_limiter: AsyncRateLimiter


@runtime_checkable
class Enricher(Protocol):
    """Take a DomainEntity, return a (possibly mutated) one.

    Enrichers should be:
      - Pure functions where possible (no side effects)
      - Idempotent — re-running produces same output
      - Bounded — never fetch unless necessary; respect RecordFailedRoute pattern
    """

    name: str

    async def enrich(self, entity: DomainEntity, ctx: EnrichmentContext) -> DomainEntity:
        ...
