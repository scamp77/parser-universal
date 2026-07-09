# Architecture

## 5-layer model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Layer 5: Orchestrator / CLI                                                │
│    ParserOrchestrator (parsers/orchestrator/orchestrator.py)                │
│    parser-cli run / orchestrate / run-config                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  Layer 4: Sink (persist)                                                    │
│    PostgresSink (psycopg3 + ON CONFLICT + JSONB || + soft-delete)           │
│    FailureSink (attempts counter, idempotent UPSERT)                        │
│    DryRunSink (default for tests)                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  Layer 3: Enrich (post-fetch side-effects)                                  │
│    BrouterEnricher (river profile; LON-LAT order convention)                │
│    Coords helpers (center=[LAT,LON] vs placemark={LON,LAT} canonicalization)│
├─────────────────────────────────────────────────────────────────────────────┤
│  Layer 2: Normalize (canonical shape)                                       │
│    bbox classifier (BY/KZ/UA/RU; KZ+UA before RU ordering)                 │
│    coord_canonical (DMS + decimal + Yandex/Google/OSM/BRouter dispatch)     │
├─────────────────────────────────────────────────────────────────────────────┤
│  Layer 1: Input adapters                                                    │
│    url / html / gpx / api / overpass                                        │
│    All return RawRecord (canonical schema: source, source_id, raw, ...)    │
└─────────────────────────────────────────────────────────────────────────────┘
       ↓↓↓↓↓↓↓↓↓↓↓↓ cross-cutting infra ↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓
  SafeFetcher (httpx + curl_cffi + Jina fallback chain)
  RateLimiter (sync threading + async asyncio)
  RetryPolicy (Jina-retry pattern, exponential backoff, 4xx ≠ retry)
  Observability (structlog + daily_source_log + rate_limiter_stats)
  Parallel batch (asyncio.gather + Semaphore, Phase 4)
```

## Postgres schema

`PostgresSink.upsert()` requires this shape (configurable per-instance):

```sql
CREATE TABLE IF NOT EXISTS entities (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    geom            JSONB,                -- {type:Point, coordinates:[lon,lat]}
    attrs           JSONB NOT NULL DEFAULT '{}'::jsonb,
    bbox_country    TEXT,
    confidence      REAL DEFAULT 1.0,
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    removed_at      TIMESTAMPTZ,           -- soft-delete (benz durable rule)
    UNIQUE (source, source_id)
);
```

`FailureSink.record()` writes to `raw_routes_failed` (matches sup-app convention):

```sql
CREATE TABLE IF NOT EXISTS raw_routes_failed (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    title           TEXT,
    url             TEXT,
    geom            JSONB,
    failure_stage   TEXT NOT NULL,
    failure_detail  TEXT,
    attempts        INT NOT NULL DEFAULT 1,
    first_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, source_id)
);
```

`DailySourceLog.write()` writes one row per parser-run:

```sql
CREATE TABLE IF NOT EXISTS daily_source_log (
    id           BIGSERIAL PRIMARY KEY,
    source       TEXT NOT NULL,
    rows_added   INT NOT NULL DEFAULT 0,
    rows_updated INT NOT NULL DEFAULT 0,
    http_status  INT,
    error        TEXT,                     -- diagnostics packed as 'k=v|k=v'
    duration_ms  INT
);
```

## Idempotency guarantees

- `PostgresSink.upsert()` on conflict: JSONB `||` merge (preserves prior keys),
  `last_seen_at = NOW()`, clears `removed_at = NULL` (re-activation).
- `FailureSink.record()` on conflict: `attempts = ... + 1`, `last_attempt_at = NOW()`.
- Re-running `parser-cli orchestrate` with identical inputs is a no-op
  beyond the `last_seen_at` / `attempts` updates — safe by default.

## Persistent HTTP client (Phase 4)

For batch jobs (≥100 URLs), wrap the run in `PersistentHTTPClient` to
reuse a single connection pool:

```python
async with PersistentHTTPClient() as p:
    fetcher = SafeFetcher(strategies=[make_persistent_httpx(p)])
    # ...run orchestrator with this fetcher
```

Each `httpx.AsyncClient` open costs ~100-300ms of TCP+TLS handshake. Phase 4
DoD: 1000 records in <30s.

## Parallel batch (Phase 4)

Set `parallel.workers > 1` in YAML to fan out via `asyncio.gather + Semaphore`:

```yaml
parallel:
  workers: 4
  batch_size: 32
```

Per memory rule: **never** use multiprocessing — single event loop keeps
the connection pool coherent (no pool-init races).
