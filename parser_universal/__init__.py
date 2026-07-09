"""parser-universal: cross-project reusable parser framework.

Phase 2 — Layer 5 (Orchestrator) + Layer 4 (Sinks) + Cross-cutting Observability.

Public API surface:
    types       — RawRecord, DomainEntity, FetchResult, RetryPolicy
    fetcher     — SafeFetcher + strategies (httpx, jina_fallback)
    rate_limiter — Async + Sync (from sup-app)
    retry       — RetryPolicy + default
    adapters    — InputAdapter protocol + url_dispatch, html, gpx, api
    normalizers — bbox classifier + coord canonicalization
    sinks       — PostgresSink, FailureSink (psycopg3 + ON CONFLICT + soft-delete)
    db          — get_conn, transaction
    observability — structlog, DailySourceLog, RateLimiterStats
    orchestrator  — ParserOrchestrator + DryRunSink (Phase 2)
"""

from __future__ import annotations

__version__ = "0.2.0"

from parser_universal.types import (
    DomainEntity,
    FetchResult,
    RawRecord,
    RetryPolicy,
)

__all__ = [
    "__version__",
    "DomainEntity",
    "FetchResult",
    "RawRecord",
    "RetryPolicy",
]
