# parser-universal

Cross-project reusable parser framework — **Phase 4** (Stabilization).

5-layer architecture (Input adapters → Normalize → Enrich → Sink → Orchestrator)
with cross-cutting SafeFetcher, RateLimiter, RetryPolicy, structlog observability,
persistent httpx client, and asyncio.gather parallel batching.

## Stack

- **Python:** 3.11+
- **License:** Proprietary (internal use only — not for distribution)
- **Status:** Phase 4 SHIPPED — 121 tests passing
- **Design doc:** `/root/benz/research/PARSER_UNIVERSAL_PLAN.md` (549 lines)
- **Session handoff:** `/root/benz/SESSION_NEXT_PROMPT_PARSER_UNIVERSAL.md`

## Installation (editable)

```bash
cd /root/parser-universal
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,db]"   # db extra pulls psycopg[binary]
```

## CLI

```bash
# Single record (no sink)
parser-cli run --adapter gpx --locator tests/data/sample.gpx

# Full pipeline driven by YAML
parser-cli run-config configs/smoke.yaml

# Manual orchestration
parser-cli orchestrate --adapter url \
    --locators "https://yandex.ru/maps/?ll=37.6173,55.7558,https://maps.google.com/?q=55.7558,37.6173" \
    --sink dryrun

# Validate config without running
parser-cli validate-config configs/smoke.yaml
```

## Postgres

```bash
export POSTGRES_DSN='postgresql://user:pass@host:5432/dbname'
parser-cli run-config configs/minfin_pipeline.yaml --sink postgres
```

Schema (see `docs/architecture.md` for full DDL):

```sql
CREATE TABLE IF NOT EXISTS entities (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL, source_id TEXT NOT NULL,
    entity_type TEXT NOT NULL, geom JSONB, attrs JSONB NOT NULL DEFAULT '{}'::jsonb,
    bbox_country TEXT, confidence REAL DEFAULT 1.0,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    removed_at TIMESTAMPTZ,         -- soft-delete (benz durable rule)
    UNIQUE (source, source_id)
);
```

## CLI subcommands summary

| Subcommand         | Purpose                                            |
|--------------------|----------------------------------------------------|
| `run`              | Single adapter + locator → JSON record             |
| `orchestrate`      | Full Layer 1-5 chain with --enricher support       |
| `run-config`       | Full Layer 1-5 chain driven by YAML config         |
| `validate-config`  | YAML schema check, no run                          |

## Tests

```bash
pip install -e ".[dev,db]"
pytest             # 121 tests in 2.4s
```

## Documentation

```bash
pip install -e ".[docs]"
mkdocs serve       # preview at http://localhost:8000
mkdocs build       # generate site/ for hosting
```

Or browse the source: `docs/{index,quickstart,architecture,adapters,observability,roadmap}.md`.

## What's shipped

**Phase 1 (MVP):**
- `types.py` (RawRecord / DomainEntity / FetchResult / RetryPolicy)
- `fetcher/safe.py` + strategies (httpx, jina_fallback)
- `rate_limiter/{async,sync}_impl.py` — 1:1 from sup-app
- `adapters/{base,html,gpx,api,url_dispatch}.py`
- `normalizers/{bbox,coord_canonical}.py`

**Phase 2 (Production):**
- `sinks/{postgres,failure}.py` — psycopg3 + ON CONFLICT + JSONB || + soft-delete
- `db/__init__.py` — psycopg3 `get_conn` + `transaction()`
- `observability/{structlog_setup,daily_source_log,rate_limiter_stats}.py`
- `orchestrator/orchestrator.py` — Layer 5

**Phase 3 (Coverage):**
- `enrichers/{base,coords,brouter}.py` — BrouterEnricher + OSM coord canonicalization
- `adapters/overpass.py` — `OverpassAdapter` (default mirror: `maps.mail.ru`)

**Phase 4 (Stabilization):**
- `fetcher/persistent.py` — `PersistentHTTPClient` (10x batch speedup)
- `fetcher/strategies/httpx_persistent_impl.py` — `make_persistent_httpx()`
- `parallel.py` — `gather_with_semaphore()` (asyncio.gather + Semaphore)
- `config_loader.py` — YAML declarative config + `validate_config()`
- `cli/run_config_cmd.py` — `parser-cli run-config`
- `mkdocs.yml` + 6 docs pages

## Source-of-truth copies

| Component | Source | LOC |
|---|---|---|
| RateLimiter sync | `/root/sup-app/sup-app/scripts/import_wikiloc_ratelimit.py` | 90 |
| bbox + DMS regex | `/root/sup-app/sup-app/scripts/import_route/parsers.py` | ~80 |
| URL dispatch quirks | same file | ~120 |
| BRouter | `/root/sup-app/sup-app/app/importers/brouter.py` | 174 |
| v2.raw_routes_failed | `/root/sup-app/sup-app/scripts/import_route/track.py:215-256` | ~50 |
| daily_source_log | `/root/benz/parsers/load_minfin_prices.py:263-275` | ~12 |

## Phase 4 DoD — verified

- 121 tests pass in 2.4s (was 98 in Phase 3)
- 1000-record perf budget: <30s (mock network; in practice <5s)
- `parser-cli run-config configs/smoke.yaml` exit 0, JSON output, persistent client closed cleanly
- mkdocs.yml + 6 docs pages (index, quickstart, architecture, adapters, observability, roadmap)
