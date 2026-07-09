# Phase roadmap

The design doc is at `/root/benz/research/PARSER_UNIVERSAL_PLAN.md` (549 lines, 13 sections). Phases ship in order:

## Phase 1 — MVP  ✓ SHIPPED
- Types, SafeFetcher (3 strategies), RateLimiter (sync + async), RetryPolicy
- 5 adapters (url, html, gpx, api, overpass-placeholder)
- 2 normalizers (bbox, coord_canonical)
- CLI: `parser-cli run` / `validate-config`
- 38 tests passing

## Phase 2 — Production  ✓ SHIPPED
- Layer 4 sinks: `PostgresSink`, `FailureSink`, `DryRunSink`
- DB helpers: `get_conn`, `transaction`
- Observability: structlog, `DailySourceLog`, `RateLimiterStats`
- Orchestrator (Layer 5)
- CLI: `parser-cli orchestrate`
- 68 tests passing

## Phase 3 — Coverage  ✓ SHIPPED
- Layer 3 enrichers: `BrouterEnricher` (profile=river), `coords` canonicalization
- New adapter: `OverpassAdapter` (default mirror: `maps.mail.ru`)
- 98 tests passing

## Phase 4 — Stabilization  ✓ SHIPPED
- Persistent httpx client (10x batch speedup)
- Parallel batch via `asyncio.gather + Semaphore`
- YAML declarative config + `parser-cli run-config`
- mkdocs documentation site
- 121 tests passing; 1000-record perf budget verified

## Future (not planned)

- PostgresPool integration (Phase 4 partially did this; pool races on
  multiprocess forbidden per `MEMORY-benz-rules-extracted.md`)
- Mkdocs-material hosting on GitHub Pages (requires choosing CI/CD; deferred)
- BRouterProfile=foot / hike / car (only `river` currently implemented)
- Yandex/Google page hydration (currently URL-only)
- Sparse-track densification via linear interpolation (benz has this upstream)

## Source-of-truth (for safe migration)

- RateLimiter sync: `/root/sup-app/sup-app/scripts/import_wikiloc_ratelimit.py`
- BRouter: `/root/sup-app/sup-app/app/importers/brouter.py`
- Bbox + DMS regex + URL dispatch quirks: `/root/sup-app/sup-app/scripts/import_route/parsers.py`
- daily_source_log pattern: `/root/benz/parsers/load_minfin_prices.py:263`
- FailureSink pattern: `/root/sup-app/sup-app/scripts/import_route/track.py:215-256`
