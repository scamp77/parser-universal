# parser-universal

**Cross-project reusable parser framework** — turn any HTML / JSON / URL / API
/ GPX / Overpass source into canonical `DomainEntity` rows, with
rate-limiting, retries, observability, and idempotent PostgresSink built in.

5-layer architecture: Input adapters → Normalize → Enrich → Sink → Orchestrator.
Cross-cutting: SafeFetcher (multi-strategy HTTP), RateLimiter (sync + async),
RetryPolicy (jina_retry pattern), observability (structlog + daily_source_log
+ rate_limiter_stats).

## Quickstart

```bash
pip install parser-universal

# Single record (no sink)
parser-cli run --adapter gpx --locator sample.gpx

# Full pipeline from YAML (Phase 4)
parser-cli run-config configs/smoke.yaml

# Validate a config without running
parser-cli validate-config my-config.yaml

# Run with custom adapter + sink
parser-cli orchestrate --adapter url \
    --locators "https://yandex.ru/maps/?ll=37.6173,55.7558,https://maps.google.com/?q=55.7558,37.6173" \
    --sink dryrun
```

## Supported adapters

- `url` — Yandex/Google/OSM/BRouter URL → coordinates
- `gpx` — local or remote .gpx → track_points + waypoints
- `html` — static HTML pages
- `api` — generic JSON APIs (auth headers supported)
- `overpass` — OpenStreetMap Overpass API (default mirror: `maps.mail.ru`)

## Supported enrichers

- `brouter` — fills `attrs['track']` via the public BRouter service
  (`profile=river` by default; LON-LAT order, GeoJSON in / out)

## Sinks

- `dryrun` — in-memory (default for tests)
- `postgres` — psycopg3 with `ON CONFLICT + JSONB || merge + soft-delete`

## Status (Phase 4)

- 121 unit + integration tests passing in 2.4s
- Persistent httpx client (10x speedup on batch)
- Parallel workers via `asyncio.gather + Semaphore`
- YAML declarative pipeline config
- Observability: structlog + `daily_source_log` + `rate_limiter_stats`

See [Architecture](architecture.md) for the full Layer model.
