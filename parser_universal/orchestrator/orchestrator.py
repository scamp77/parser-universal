"""Layer 5: ParserOrchestrator — wires Layer 1-4 + observability together.

Phase 2 MVP. Reads from a SourceIterator, runs each item through
fetch → normalize → enrich (TODO) → sink, with optional FailureSink side-effect
on errors. Calls DailySourceLog once at end of run.

Usage:
    orch = ParserOrchestrator(
        adapter=URLCoordAdapter(),
        normalizer=None,            # optional — skipped for URL adapter
        sinks=[PostgresSink(conn, table='entities')],
        failure_sink=FailureSink(conn),
        daily_log=DailySourceLog(conn),
        source_name='url_dispatch',
    )
    result = await orch.run(['yandex_url', 'google_url'])
    assert result.rows_failed == 0
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Iterable, Protocol, runtime_checkable

from parser_universal.adapters.base import InputAdapter
from parser_universal.enrichers.base import Enricher, EnrichmentContext
from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.observability.daily_source_log import DailySourceLog
from parser_universal.observability.structlog_setup import get_logger
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter
from parser_universal.sinks.base import EntityResult, Sink
from parser_universal.sinks.failure import FailureSink
from parser_universal.types import DomainEntity, RawRecord

log = get_logger(__name__)


@runtime_checkable
class Normalizer(Protocol):
    """Optional Layer 2 — converts RawRecord → DomainEntity.

    Adapters that already return structure usable as a DomainEntity (e.g. URL
    dispatch which only provides coord_hint) can skip this step.
    """

    entity_type: str

    def normalize(self, raw: RawRecord) -> DomainEntity | None: ...


@dataclass
class OrchestratorResult:
    """Counters returned from `Orchestrator.run()`."""

    rows_total: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    rows_failed: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0


class DryRunSink:
    """In-memory sink for tests / smoke-runs. Implements Sink protocol."""

    name = "dryrun"

    def __init__(self) -> None:
        self.records: list[DomainEntity] = []

    async def upsert(self, entity: DomainEntity) -> EntityResult:
        self.records.append(entity)
        return EntityResult.INSERTED


class ParserOrchestrator:
    """Orchestrates a parser run end-to-end with observability."""

    def __init__(
        self,
        *,
        adapter: InputAdapter,
        normalizer: Normalizer | None = None,
        sinks: list[Sink] | None = None,
        failure_sink: FailureSink | None = None,
        daily_log: DailySourceLog | None = None,
        fetcher: SafeFetcher | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
        enrichers: list["Enricher"] | None = None,
        source_name: str = "unknown",
    ) -> None:
        self.adapter = adapter
        self.normalizer = normalizer
        self.sinks: list[Sink] = sinks or [DryRunSink()]
        self.failure_sink = failure_sink
        self.daily_log = daily_log
        self.fetcher = fetcher or adapter.source_safe_fetcher()
        self.rate_limiter = rate_limiter or AsyncRateLimiter(rate_per_sec=2.0, burst=4)
        self.enrichers: list[Enricher] = enrichers or []
        self.source_name = source_name

    async def run(self, locators: Iterable) -> OrchestratorResult:
        """Fetch → (normalize) → enrich → persist each locator.

        Layer-by-layer:
          1. adapter.fetch_one(locator) → RawRecord
          2. normalizer.normalize(raw)   → DomainEntity  (optional)
          3. each enricher.enrich(entity, ctx) → DomainEntity (Phase 3)
          4. each sink.upsert(entity)    → EntityResult

        Idempotent — safe to re-run.
        """
        t0 = time.monotonic()
        ctx = EnrichmentContext(
            fetcher=self.fetcher,
            rate_limiter=self.rate_limiter,
        )
        result = OrchestratorResult()

        for locator in locators:
            result.rows_total += 1
            http_status: int | None = None
            error: str | None = None
            raw: RawRecord | None = None

            try:
                raw = await self.adapter.fetch_one(
                    locator,
                    fetcher=self.fetcher,
                    rate_limiter=self.rate_limiter,
                )
            except Exception as exc:  # noqa: BLE001
                error = f"fetch: {type(exc).__name__}: {exc}"
                log.warning("orchestrator.fetch_failed", source=self.source_name, locator=str(locator), error=error)

            if raw is None:
                # Skip (e.g. cache hit but parse-failed, or unknown URL).
                if error is None:
                    error = "adapter_returned_none"
                result.rows_skipped += 1
                self._record_failure(
                    locator, error, stage="fetch",
                )
                result.errors.append(error)
                continue

            # Normalize (optional).
            entity: DomainEntity | None = None
            if self.normalizer is not None:
                try:
                    entity = self.normalizer.normalize(raw)
                except Exception as exc:  # noqa: BLE001
                    error = f"normalize: {type(exc).__name__}: {exc}"
                    result.rows_failed += 1
                    self._record_failure(
                        locator, error, stage="normalize", raw=raw,
                    )
                    result.errors.append(error)
                    continue
                if entity is None:
                    error = "normalizer_returned_none"
                    result.rows_skipped += 1
                    self._record_failure(
                        locator, error, stage="normalize", raw=raw,
                    )
                    result.errors.append(error)
                    continue
            else:
                # No normalizer: synthesize entity from raw (URL adapter etc.).
                from parser_universal.sinks.postgres import PostgresSink  # noqa: F401
                entity = DomainEntity(
                    entity_type="raw",
                    source=raw.source,
                    source_id=raw.source_id,
                    geom=raw.coord_hint,
                    attrs=raw.raw,
                )

            # Layer 3: Enrich (Phase 3). Run each enricher in order;
            # failures are logged but do not abort the row.
            for enricher in self.enrichers:
                try:
                    entity = await enricher.enrich(entity, ctx)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "orchestrator.enrich_failed",
                        enricher=enricher.name,
                        source=self.source_name,
                        error=str(exc),
                    )

            # Persist via each sink.
            for sink in self.sinks:
                try:
                    outcome = await sink.upsert(entity)
                except Exception as exc:  # noqa: BLE001
                    error = f"persist[{sink.name}]: {type(exc).__name__}: {exc}"
                    result.rows_failed += 1
                    self._record_failure(
                        locator, error, stage="persist", raw=raw, entity=entity,
                    )
                    result.errors.append(error)
                    continue
                if outcome == EntityResult.INSERTED:
                    result.rows_inserted += 1
                elif outcome == EntityResult.UPDATED:
                    result.rows_updated += 1
                elif outcome == EntityResult.SKIPPED:
                    result.rows_skipped += 1
                elif outcome == EntityResult.FAILED:
                    result.rows_failed += 1

        result.duration_ms = int((time.monotonic() - t0) * 1000)

        # daily_source_log
        if self.daily_log is not None:
            try:
                self.daily_log.write(
                    source=self.source_name,
                    rows_added=result.rows_inserted,
                    rows_updated=result.rows_updated,
                    http_status=http_status,
                    error=result.errors[0] if result.errors else None,
                    duration_ms=result.duration_ms,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("orchestrator.daily_log_write_failed", error=str(exc))

        log.info(
            "orchestrator.run_done",
            source=self.source_name,
            total=result.rows_total,
            inserted=result.rows_inserted,
            updated=result.rows_updated,
            skipped=result.rows_skipped,
            failed=result.rows_failed,
            duration_ms=result.duration_ms,
        )
        return result

    def _record_failure(
        self,
        locator,
        error: str,
        *,
        stage: str,
        raw: RawRecord | None = None,
        entity: DomainEntity | None = None,
    ) -> None:
        if self.failure_sink is None:
            return
        # Synthesize a minimal RawRecord if adapter failed before any fetch.
        rr = raw
        if rr is None:
            rr = RawRecord(
                source=self.source_name,
                source_id=str(locator),
                raw={"locator": str(locator)},
            )
        try:
            self.failure_sink.record(rr, stage=stage, detail=error)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            log.warning("orchestrator.failure_sink_write_failed", error=str(exc))


__all__ = ["ParserOrchestrator", "OrchestratorResult", "DryRunSink", "Normalizer"]
